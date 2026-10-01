/* tokenize_plugin.c — forkrun C plugin for LLM tokenization (W-PY25).
 *
 * Same algorithm as tokenize_payload.Tokenizer, compiled:
 * whitespace split (no case folding), vocab hash lookup, one
 * suffix-strip (first match in SUFFIXES order, len > sl+2),
 * stem+suffix emit, else UNK(0); doc stats; quality filter
 * (20 <= n <= 1000 tokens, diversity >= 0.1).
 *
 * Input: RAW borrowed window when FLAG_RAW granted, else pread.
 * Output: stdout (captured + framed by the shim). Records joined
 * with every doc (valid or blank-filtered) terminated by '\n',
 * so newline counts are exact totals. A zero-line batch writes
 * nothing (shim emits no record, like None).
 *
 * Conventions vs Python (validated, not assumed):
 * - malformed lines skip (structural gate + required-field checks)
 * - missing/non-string text skips (Python: "" -> 0 tokens -> filter)
 * - suffix table AND order identical to tokenize_payload.SUFFIXES
 * - diversity uses round-half-even (long-double scaled; see below)
 * - doc_id: integer when parseable, else raw token (quoted if
 *   string) or null when missing — mirrors Python passthrough
 * - overlong words (>511 bytes) short-circuit to UNK: no vocab
 *   word exceeds ~50 bytes, so no stem of one can hit either
 *   (provably equivalent, avoids unbounded stack copies)
 * - data assumption: no backslash escapes inside string values
 *   (holds for generator output; see ml_plugin_medium.c)
 *
 * Build: gcc -O3 -shared -fPIC -march=native -I<repo>/ring_loadables
 *        -o tokenize_plugin.so tokenize_plugin.c -lm
 */

#include "forkrun_plugin.h"

#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Dialect 2 + RAW borrowed window (reserved[0]). */
int forkrun_use_ctx = (int)(FORKRUN_CTX_ENABLE | FORKRUN_CTX_FLAG_RAW);

/* Suffix table AND ORDER mirror tokenize_payload.SUFFIXES exactly. */
static const char *SUFFIXES[] = {
    "ing", "tion", "ness", "ment", "able", "ible", "ful", "less",
    "ly", "er", "est", "ed", "es", "s",
};
#define N_SUFFIXES (sizeof(SUFFIXES) / sizeof(SUFFIXES[0]))

#define MIN_TOKENS 20
#define MAX_TOKENS 1000
#define MIN_DIVERSITY 0.1
#define MAX_WORD 511
#define MAX_TOKENS_DOC 8192

/* ---- Vocabulary hash table (chained, 64k buckets, ~30k words) ---- */

#define VT_BITS 16
#define VT_SIZE (1u << VT_BITS)

typedef struct ventry {
    struct ventry *next;
    uint32_t id;
    size_t len;
    char word[];
} ventry_t;

static ventry_t *g_vtab[VT_SIZE];
static int g_vocab_loaded = 0;

static uint32_t hash_bytes(const char *s, size_t n) {
    /* FNV-1a 32-bit. */
    uint32_t h = 2166136261u;
    size_t i;

    for (i = 0; i < n; i++) {
        h ^= (uint32_t)(unsigned char)s[i];
        h *= 16777619u;
    }
    return h;
}

/* Returns id, or 0 (UNK) on miss. Words over MAX_WORD short-circuit:
 * provably equivalent (no vocab word nor any of its stems is that
 * long), and it bounds the lookup to stack-friendly sizes. */
static uint32_t vocab_lookup(const char *s, size_t n) {
    uint32_t h;
    ventry_t *e;

    if (n == 0 || n > MAX_WORD)
        return 0;
    h = hash_bytes(s, n) & (VT_SIZE - 1);
    for (e = g_vtab[h]; e; e = e->next) {
        if (e->len == n && memcmp(e->word, s, n) == 0)
            return e->id;
    }
    return 0;
}

static int vocab_insert(const char *s, size_t n, uint32_t id) {
    uint32_t h;
    ventry_t *e;

    if (n == 0 || n > MAX_WORD || id == 0)
        return -1;
    h = hash_bytes(s, n) & (VT_SIZE - 1);
    e = (ventry_t *)malloc(sizeof(ventry_t) + n + 1);
    if (!e)
        return -1;
    e->next = g_vtab[h];
    e->id = id;
    e->len = n;
    memcpy(e->word, s, n);
    e->word[n] = '\0';
    g_vtab[h] = e;
    return 0;
}

/* Load "id\tword" vocabulary (once per worker process). */
static int vocab_load(const char *path) {
    FILE *fh;
    char line[512];

    if (g_vocab_loaded)
        return 0;
    fh = fopen(path, "r");
    if (!fh)
        return -1;
    while (fgets(line, sizeof(line), fh)) {
        char *tab = strchr(line, '\t');
        char *nl;
        size_t wlen;
        unsigned long id;

        if (!tab)
            continue;
        *tab = '\0';
        id = strtoul(line, NULL, 10);
        nl = strchr(tab + 1, '\n');
        if (nl)
            *nl = '\0';
        wlen = strlen(tab + 1);
        if (id > 0 && id < UINT32_MAX && wlen > 0)
            vocab_insert(tab + 1, wlen, (uint32_t)id);
    }
    fclose(fh);
    g_vocab_loaded = 1;
    return 0;
}

/* ---- Small JSON helpers (same shape as ml_plugin_medium.c) ---- */

typedef struct {
    const char *p;
    size_t n;
    int is_str;
} jval_t;

static const char *skip_ws(const char *p, const char *end) {
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r'))
        p++;
    return p;
}

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

static int parse_int(const jval_t *v, long long *dst) {
    char buf[32];
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

/* Structural gate (see ml_plugin_medium.c): truncated lines fail. */
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

/* round-half-even to 4 decimals via long-double scaling (see
 * ml_plugin_heavy.c: double scaling double-rounds exact halves). */
static double round4_even(double v) {
    long double s = (long double)v * 10000.0L;
    long double f = floorl(s);
    long double frac = s - f;
    long double r;

    if (frac < 0.5L) {
        r = f;
    } else if (frac > 0.5L) {
        r = f + 1.0L;
    } else {
        r = (fmodl(f, 2.0L) == 0.0L) ? f : f + 1.0L;
    }
    return (double)(r / 10000.0L);
}

static void fmt_r4(double v, char *buf, size_t cap) {
    double r = round4_even(v);
    char tmp[64];
    size_t n, e;

    snprintf(tmp, sizeof(tmp), "%.4f", r);
    n = strlen(tmp);
    e = n;
    if (strchr(tmp, '.') != NULL) {
        while (e > 0 && tmp[e - 1] == '0')
            e--;
        if (e > 0 && tmp[e - 1] == '.')
            e--;
    }
    if (e == 0 || (e == 1 && tmp[0] == '-')) {
        snprintf(buf, cap, "0.0");
        return;
    }
    if (e >= cap)
        e = cap - 1;
    memcpy(buf, tmp, e);
    buf[e] = '\0';
    if (strchr(buf, '.') == NULL && strchr(buf, 'e') == NULL &&
        strchr(buf, 'E') == NULL) {
        size_t l = strlen(buf);
        if (l + 2 < cap) {
            buf[l] = '.';
            buf[l + 1] = '0';
            buf[l + 2] = '\0';
        }
    }
}

/* ---- Output buffer (static, worker reuse) ---- */

static char *g_out = NULL;
static size_t g_out_cap = 0;

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

/* Manual uint64 -> decimal (exact, fast; snprintf-free hot path). */
static size_t u64toa(uint64_t v, char *buf) {
    char tmp[24];
    size_t n = 0, i;

    if (v == 0) {
        buf[0] = '0';
        return 1;
    }
    while (v > 0) {
        tmp[n++] = (char)('0' + (v % 10));
        v /= 10;
    }
    for (i = 0; i < n; i++)
        buf[i] = tmp[n - 1 - i];
    return n;
}

/* One document; returns bytes appended, -1 skip, -2 overrun. */
static long emit_doc(const char *line, const char *lend, char **dst,
                     size_t *left) {
    static uint32_t toks[MAX_TOKENS_DOC];
    jval_t textf, didf;
    const char *tp;
    size_t tn;
    size_t n = 0, u = 0;
    const char *p, *end;
    char *o = *dst;
    size_t rem = *left;
    char div_b[32];
    size_t i;
    long w;
    int have_did = 0;
    long long did_v = 0;
    const char *did_p = NULL;
    size_t did_n = 0;

    if (find_field(line, lend, "text", &textf) != 0 || !textf.is_str)
        return -1; /* missing/non-string text: "" -> 0 tokens */
    tp = textf.p;
    tn = textf.n;
    p = tp;
    end = tp + tn;

    /* Whitespace split + vocab/subword/UNK (mirrors Tokenizer). */
    while (p < end && n < MAX_TOKENS_DOC) {
        while (p < end && isspace((unsigned char)*p))
            p++;
        if (p >= end)
            break;
        {
            const char *ws = p;
            while (ws < end && !isspace((unsigned char)*ws))
                ws++;
            {
                size_t wl = (size_t)(ws - p);
                uint32_t id = vocab_lookup(p, wl);
                if (id > 0) {
                    toks[n++] = id;
                } else {
                    size_t s;
                    int done = 0;
                    /* First matching suffix wins ONLY when its stem
                     * hits (Python continues past stem misses). */
                    for (s = 0; s < N_SUFFIXES; s++) {
                        size_t sl = strlen(SUFFIXES[s]);
                        if (wl > sl + 2 &&
                            memcmp(p + wl - sl, SUFFIXES[s], sl)
                            == 0) {
                            uint32_t sid =
                                vocab_lookup(p, wl - sl);
                            if (sid > 0) {
                                toks[n++] = sid;
                                if (n < MAX_TOKENS_DOC)
                                    toks[n++] = vocab_lookup(
                                        SUFFIXES[s], sl);
                                done = 1;
                                break;
                            }
                        }
                    }
                    if (!done)
                        toks[n++] = 0;
                }
            }
            p = ws;
        }
    }

    if (n < MIN_TOKENS || n > MAX_TOKENS)
        return -1;
    /* Unique count via sort (n <= ~1000; qsort overkill — insertion). */
    {
        static uint32_t srt[MAX_TOKENS_DOC];
        memcpy(srt, toks, n * sizeof(uint32_t));
        for (i = 1; i < n; i++) {
            uint32_t key = srt[i];
            long long j = (long long)i - 1;
            while (j >= 0 && srt[j] > key) {
                srt[j + 1] = srt[j];
                j--;
            }
            srt[j + 1] = key;
        }
        u = 1;
        for (i = 1; i < n; i++) {
            if (srt[i] != srt[i - 1])
                u++;
        }
    }
    {
        double div = (double)u / (double)n;
        if (div < MIN_DIVERSITY)
            return -1;
        fmt_r4(div, div_b, sizeof(div_b));
    }

    /* doc_id: integer when parseable, else raw (quoted if string)
     * or null when missing — mirrors Python passthrough. */
    if (find_field(line, lend, "doc_id", &didf) == 0) {
        long long dv;
        if (parse_int(&didf, &dv) == 0) {
            have_did = 1;
            did_v = dv;
        } else if (didf.is_str) {
            have_did = 2;
            did_p = didf.p;
            did_n = didf.n;
        } else if (didf.n > 0) {
            have_did = 3;
            did_p = didf.p;
            did_n = didf.n;
        }
    }

    /* Format: {"doc_id":D,"tokens":[...],"n_tokens":N,
     *          "n_unique":U,"diversity":X} */
    w = 0;
#define EMIT_STR(s, l)                                                 \
    do {                                                               \
        if ((size_t)w + (l) >= rem)                                    \
            return -2;                                                 \
        memcpy(o + w, (s), (l));                                       \
        w += (long)(l);                                                \
    } while (0)
#define EMIT_C(c)                                                      \
    do {                                                               \
        if ((size_t)w + 1 >= rem)                                      \
            return -2;                                                 \
        o[w++] = (c);                                                  \
    } while (0)
    {
        const char *pre = "{\"doc_id\":";
        EMIT_STR(pre, strlen(pre));
        if (have_did == 1) {
            char nb[32];
            size_t nl;
            if (did_v < 0) {
                EMIT_C('-');
                nl = u64toa((uint64_t)(-did_v), nb);
            } else {
                nl = u64toa((uint64_t)did_v, nb);
            }
            EMIT_STR(nb, nl);
        } else if (have_did == 2) {
            EMIT_C('"');
            EMIT_STR(did_p, did_n);
            EMIT_C('"');
        } else if (have_did == 3) {
            EMIT_STR(did_p, did_n);
        } else {
            EMIT_STR("null", 4);
        }
        {
            const char *mid = ",\"tokens\":[";
            EMIT_STR(mid, strlen(mid));
        }
        for (i = 0; i < n; i++) {
            char nb[24];
            size_t nl = u64toa(toks[i], nb);
            if (i > 0)
                EMIT_C(',');
            EMIT_STR(nb, nl);
        }
        {
            char tail[128];
            int tl = snprintf(tail, sizeof(tail),
                              "],\"n_tokens\":%lu,\"n_unique\":%lu,"
                              "\"diversity\":%s}",
                              (unsigned long)n, (unsigned long)u,
                              div_b);
            if (tl < 0)
                return -1;
            EMIT_STR(tail, (size_t)tl);
        }
    }
#undef EMIT_STR
#undef EMIT_C
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
            /* Separator first; KEPT when the doc skips: filtered
             * documents emit a blank segment, so output segments ==
             * input docs and totals stay exact. (Valid-doc bytes
             * are unchanged.) */
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
                r = emit_doc(ls, le, &o, &left);
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

/* Entry point: dialect-2 ctx dispatch. Input: RAW borrowed window
 * when granted, else pread(fd_in). Output: stdout. The vocabulary
 * loads once per worker from FORKRUN_VOCAB_PATH. */
int ml_tokenize(int argc, char **argv, const struct forkrun_ctx *ctx) {
    const char *data = NULL;
    size_t data_len = 0;
    char *heap = NULL;
    int rc;

    (void)argc;
    (void)argv;
    if (!ctx)
        return -1;
    if (!g_vocab_loaded) {
        const char *vp = getenv("FORKRUN_VOCAB_PATH");
        if (!vp || !vp[0] || vocab_load(vp) != 0)
            return -1;
    }
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
