/* ml_plugin_light.c — forkrun C plugin for the ML-PREP-1 benchmark.
 *
 * Same logical workload as ml_payload.process_event_light, compiled:
 * parse + validate + compact projection, per line.
 * Hand-rolled field extraction for this JSON shape (no general JSON
 * parser — same principle as vectorized native engines: exploit known
 * structure). Zero-copy input via FLAG_RAW borrowed window (pread
 * fallback when ungranted); output via stdout (captured + framed by
 * the shim, exactly like the Python path's return bytes).
 *
 * Conventions vs the Python payload (validated, not assumed):
 * - malformed lines (truncated/missing/wrong-type/garbage/empty) skip
 * - quality filter: duration_ms < 100 or unknown event_type skips
 * - computed floats (ts_n, log_dur, log_pr) use C double arithmetic
 *   with shortest-ish formatting (validated with epsilon, not bytes)
 * - pass-through floats (scr, rate) and all ints/strings are exact
 * - every record (valid or blank-filtered) terminated with
 *   '\n', so newline counts are exact totals; filtered /
 *   malformed records emit a bare '\n'. A zero-line batch
 *   writes nothing (the shim then emits no record, like None)
 * - data assumption: no backslash escapes inside string values
 *   (holds for generator output; malformed lines with escapes only
 *   diverge if they otherwise pass validation, which truncation
 *   prevents in practice — verified by the equality check)
 *
 * Build: gcc -O3 -shared -fPIC -march=native -I<repo>/ring_loadables
 *        -o ml_plugin_medium.so ml_plugin_medium.c -lm
 */

#include "forkrun_plugin.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Dialect 2 + RAW borrowed window (reserved[0]). */
int forkrun_use_ctx = (int)(FORKRUN_CTX_ENABLE | FORKRUN_CTX_FLAG_RAW);

#define BASE_TS 1700000000LL

/* Growable static output buffer (single-threaded worker reuse). */
static char *g_out = NULL;
static size_t g_out_cap = 0;

typedef struct {
    const char *p;  /* value span (inner bytes for strings) */
    size_t n;
    int is_str;     /* 1 string, 0 number/true/false/null */
} jval_t;

/* Skip ASCII spaces. */
static const char *skip_ws(const char *p, const char *end) {
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r'))
        p++;
    return p;
}

/* Find "key" at object level and span its value.
 * Returns 0 with *out set, -1 when absent/unparseable. String end
 * honors backslash escapes; objects/arrays balance with string
 * awareness. Scalars run to , } ] then rtrim. Bounded by `end`. */
static int find_field(const char *obj, const char *end, const char *key,
                      jval_t *out) {
    size_t klen = strlen(key);
    const char *p = obj;

    while (p + klen + 2 <= end) {
        if (p[0] == '"' && memcmp(p + 1, key, klen) == 0 &&
            p[1 + klen] == '"') {
            const char *v = skip_ws(p + 2 + klen, end);
            if (v >= end || *v != ':')
                return -1;
            v = skip_ws(v + 1, end);
            if (v >= end)
                return -1;
            if (*v == '"') {
                const char *s = v + 1;
                const char *q = s;
                while (q < end) {
                    if (*q == '\\' && q + 1 < end) {
                        q += 2;
                        continue;
                    }
                    if (*q == '"')
                        break;
                    q++;
                }
                if (q >= end)
                    return -1;
                out->p = s;
                out->n = (size_t)(q - s);
                out->is_str = 1;
                return 0;
            }
            if (*v == '{' || *v == '[') {
                char open = *v;
                char close = (open == '{') ? '}' : ']';
                int depth = 0;
                const char *q = v;
                while (q < end) {
                    if (*q == '"') {
                        q++;
                        while (q < end) {
                            if (*q == '\\' && q + 1 < end) {
                                q += 2;
                                continue;
                            }
                            if (*q == '"')
                                break;
                            q++;
                        }
                        if (q >= end)
                            return -1;
                        q++;
                        continue;
                    }
                    if (*q == open)
                        depth++;
                    else if (*q == close) {
                        depth--;
                        if (depth == 0) {
                            q++;
                            break;
                        }
                    }
                    q++;
                }
                if (depth != 0)
                    return -1;
                out->p = v;
                out->n = (size_t)(q - v);
                out->is_str = 0;
                return 0;
            }
            {
                const char *q = v;
                while (q < end && *q != ',' && *q != '}' && *q != ']')
                    q++;
                const char *r = q;
                while (r > v && (r[-1] == ' ' || r[-1] == '\t' ||
                                 r[-1] == '\r'))
                    r--;
                out->p = v;
                out->n = (size_t)(r - v);
                out->is_str = 0;
                return (r > v) ? 0 : -1;
            }
        }
        p++;
    }
    return -1;
}

/* Structural validity gate: balanced {}[] with string/escape
 * awareness, exactly one top-level object ending at `le`.
 * Rejects truncated lines whose needed fields happen to precede the
 * cut (Python's json.loads rejects them too — without this gate a
 * truncation after item_context would emit while Python skips).
 * Unvalidated non-needed tokens are a documented residual: lines
 * whose needed fields are all valid but some ignored field is
 * corrupt diverge (unreachable from the generator's malformed
 * shapes — verified by the equality check). */
static int json_struct_ok(const char *p, const char *end) {
    int depth = 0;
    int rooted = 0;
    const char *q = p;

    if (p >= end || *p != '{')
        return -1;
    while (q < end) {
        if (*q == '"') {
            q++;
            while (q < end) {
                if (*q == '\\' && q + 1 < end) {
                    q += 2;
                    continue;
                }
                if (*q == '"')
                    break;
                q++;
            }
            if (q >= end)
                return -1;
            q++;
            continue;
        }
        if (*q == '{' || *q == '[') {
            depth++;
        } else if (*q == '}' || *q == ']') {
            depth--;
            if (depth < 0)
                return -1;
            if (depth == 0)
                rooted++;
        }
        q++;
    }
    if (depth != 0 || rooted != 1)
        return -1;
    return 0;
}

/* Strict ^-?[0-9]+$ integer parse (wrong-type values fail closed,
 * matching Python's isinstance rejection). */
static int parse_int(const jval_t *v, long long *dst) {    char buf[32];
    size_t i;

    if (v->is_str || v->n == 0 || v->n >= sizeof(buf))
        return -1;
    memcpy(buf, v->p, v->n);
    buf[v->n] = '\0';
    if (buf[0] == '-' && v->n == 1)
        return -1;
    for (i = (buf[0] == '-') ? 1 : 0; i < v->n; i++) {
        if (buf[i] < '0' || buf[i] > '9')
            return -1;
    }
    *dst = strtoll(buf, NULL, 10);
    return 0;
}

static int encode_event(const char *s, size_t n) {
    if (n == 4 && memcmp(s, "view", 4) == 0)
        return 0;
    if (n == 5 && memcmp(s, "click", 5) == 0)
        return 1;
    if (n == 6 && memcmp(s, "scroll", 6) == 0)
        return 2;
    if (n == 5 && memcmp(s, "hover", 5) == 0)
        return 3;
    if (n == 8 && memcmp(s, "purchase", 8) == 0)
        return 4;
    if (n == 4 && memcmp(s, "skip", 4) == 0)
        return 5;
    return -1;
}

static int encode_device(const char *s, size_t n) {
    if (n == 3 && memcmp(s, "ios", 3) == 0)
        return 0;
    if (n == 7 && memcmp(s, "android", 7) == 0)
        return 1;
    if (n == 3 && memcmp(s, "web", 3) == 0)
        return 2;
    if (n == 7 && memcmp(s, "desktop", 7) == 0)
        return 3;
    if (n == 6 && memcmp(s, "tablet", 6) == 0)
        return 4;
    return -1;
}

/* Append helpers (buffer pre-sized to batch length; the batch is
 * re-processed from scratch on the (unreachable in practice)
 * overrun — process_data is a pure function of its input). */
static int out_grow(size_t need) {
    size_t cap = g_out_cap ? g_out_cap : (1u << 18);
    char *nb;

    while (cap < need)
        cap *= 2;
    nb = (char *)realloc(g_out, cap);
    if (!nb)
        return -1;
    g_out = nb;
    g_out_cap = cap;
    return 0;
}

/* One record; returns bytes appended or -1 to skip the line. */
static long emit_light(const char *line, const char *lend, char **dst,
                       size_t *left) {
    jval_t eid, uid, iid, ts, et, dev, dur;
    long long ts_v, dur_v, uid_v, iid_v;
    int et_c, dev_c;
    char *o = *dst;
    size_t rem = *left;
    int w;
    char num1[32], num2[32];

    /* Required fields (missing -> skip). Light keys are short. */
    if (find_field(line, lend, "eid", &eid) != 0 || !eid.is_str)
        return -1;
    if (find_field(line, lend, "uid", &uid) != 0)
        return -1;
    if (parse_int(&uid, &uid_v) != 0)
        return -1;
    if (find_field(line, lend, "iid", &iid) != 0)
        return -1;
    if (parse_int(&iid, &iid_v) != 0)
        return -1;
    if (find_field(line, lend, "ts", &ts) != 0)
        return -1;
    if (parse_int(&ts, &ts_v) != 0)
        return -1;
    if (find_field(line, lend, "et", &et) != 0 || !et.is_str)
        return -1;
    et_c = encode_event(et.p, et.n);
    /* NOTE: light has no unknown-event filter (Python emits
     * v=-1 for unknowns); only the dur filter below can skip. */
    if (find_field(line, lend, "dev", &dev) != 0 || !dev.is_str)
        return -1;
    dev_c = encode_device(dev.p, dev.n); /* unknown -> -1 (parity) */
    /* dur missing -> default 0 -> filtered (Python parity);
     * wrong-type fails closed. */
    dur_v = 0;
    if (find_field(line, lend, "dur", &dur) == 0) {
        long long d;
        if (parse_int(&dur, &d) != 0)
            return -1;
        dur_v = d;
    }
    if (dur_v < 50)
        return -1;

    snprintf(num1, sizeof(num1), "%lld", ts_v - BASE_TS);
    snprintf(num2, sizeof(num2), "%lld", dur_v);
    w = snprintf(o, rem,
                 "{\"e\":\"%.*s\",\"u\":%lld,\"i\":%lld,\"t\":%s,"
                 "\"v\":%d,\"d\":%d}",
                 (int)eid.n, eid.p, uid_v, iid_v, num1,
                 et_c, dev_c);
    if (w < 0 || (size_t)w >= rem)
        return -2; /* buffer overrun: caller grows and retries */
    *dst = o + w;
    *left = rem - (size_t)w;
    return w;
}

static int process_once(const char *data, size_t data_len,
                          int *nrec_out) {
    const char *p = data;
    const char *end = data + data_len;
    char *o = g_out;
    size_t left = g_out_cap;
    int nrec = 0;

    while (p < end) {
        const char *nl = memchr(p, '\n', (size_t)(end - p));
        const char *lend = nl ? nl : end;
        const char *ls = p;
        const char *le = lend;
        long r;

        while (ls < le && (*ls == ' ' || *ls == '\t' || *ls == '\r'))
            ls++;
        while (le > ls && (le[-1] == ' ' || le[-1] == '\t' ||
                           le[-1] == '\r'))
            le--;
        if (le > ls) {
            /* Separator first; KEPT when the line skips: filtered /
             * malformed records emit a blank segment, so output
             * segments == input records and totals stay exact.
             * (Valid-record bytes are unchanged.) */
            if (nrec > 0) {
                if (left < 1)
                    return -2;
                *o++ = '\n';
                left--;
            }
            nrec++;
            if (json_struct_ok(ls, le) != 0) {
                /* malformed: blank segment (separator kept). */
            } else {
                r = emit_light(ls, le, &o, &left);
                if (r == -2)
                    return -2;
                if (r < 0 && r != -1) {
                    return -1;
                }
                /* r >= 0 (emitted) or r == -1 (filtered: blank kept). */
            }
        }
        p = nl ? nl + 1 : end;
    }
    /* Terminated framing: every record (valid or blank-filtered)
     * ends with '\n', so newline counts are exact totals with no
     * degenerate cases (a lone filtered record is "\n", never b"").
     * Valid-record bytes are unchanged (pure append). */
    if (nrec > 0) {
        if (left < 1)
            return -2;
        *o++ = '\n';
        left--;
    }
    *nrec_out = nrec;
    return (int)(o - g_out);
}

static int process_data(const char *data, size_t data_len) {
    int nrec = 0;
    int nbytes;

    if (g_out == NULL && out_grow(data_len > 0 ? data_len : 65536) != 0)
        return -1;
    if (g_out_cap < data_len + 64 && out_grow(data_len + 64) != 0)
        return -1;
    nbytes = process_once(data, data_len, &nrec);
    if (nbytes == -2) {
        /* Overrun (unreachable in practice: output < input per
         * record): grow 4x and restart from scratch. */
        if (out_grow(g_out_cap * 4 + 65536) != 0)
            return -1;
        nbytes = process_once(data, data_len, &nrec);
        if (nbytes < 0)
            return -1;
    } else if (nbytes < 0) {
        return -1;
    }
    if (nrec > 0)
        fwrite(g_out, 1, (size_t)nbytes, stdout);
    return 0;
}

/* Entry point: dialect-2 ctx dispatch (see _plugin.py / _shim.c).
 * Input: RAW borrowed window when granted, else pread(fd_in).
 * Output: stdout (captured + framed by the shim). */
int ml_process_light(int argc, char **argv,
                      const struct forkrun_ctx *ctx) {
    const char *data = NULL;
    size_t data_len = 0;
    char *heap = NULL;
    int rc;

    (void)argc;
    (void)argv;
    if (!ctx)
        return -1;
    if (ctx->batch_byte_length > 0) {
        if (ctx->version >= 2 &&
            (ctx->flags_granted & FORKRUN_CTX_FLAG_RAW) != 0 &&
            ctx->struct_size >= (uint32_t)(80 + sizeof(uint64_t)) &&
            ctx->reserved[0] != 0) {
            data = (const char *)(uintptr_t)ctx->reserved[0];
            data_len = (size_t)ctx->batch_byte_length;
        } else if (ctx->fd_in >= 0) {
            size_t want = (size_t)ctx->batch_byte_length;
            size_t got = 0;
            heap = (char *)malloc(want ? want : 1);
            if (!heap)
                return -1;
            while (got < want) {
                ssize_t n = pread(ctx->fd_in, heap + got, want - got,
                                  (off_t)(ctx->batch_offset + got));
                if (n < 0) {
                    if (errno == EINTR)
                        continue;
                    free(heap);
                    return -1;
                }
                if (n == 0)
                    break;
                got += (size_t)n;
            }
            data = heap;
            data_len = got;
        }
    }
    rc = (data_len > 0 && data != NULL)
         ? process_data(data, data_len) : 0;
    free(heap);
    return rc;
}
