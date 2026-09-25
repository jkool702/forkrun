/* ml_plugin_yyjson.c — forkrun C plugin for the ML-PREP-2 benchmark.
 *
 * Same logical workload as ml_plugin_medium.c (parse + validate +
 * extract + transform + quality filter, per line), with the scalar
 * hand-rolled JSON parser replaced by yyjson (SIMD parsing). All
 * input acquisition, validation semantics, output formatting, and
 * stdout framing are byte-identical to ml_plugin_medium.c by
 * construction (shared helpers copied verbatim; only the field
 * lookup core differs).
 *
 * Critical invariant: NO YYJSON_READ_INSITU. The input window is a
 * borrowed view of the shared ingress memfd (FLAG_RAW) — in-situ
 * parsing would write \0 terminators into shared memory, breaking
 * the Fallow Guarantee and fault recovery. yyjson runs here with
 * YYJSON_READ_NOFLAG (read-only) and a per-record stack pool (zero
 * heap allocation on the hot path; a malloc-backed fallback covers
 * records larger than the pool so no input size is ever refused).
 *
 * Documented residuals (same class as the scalar file's own):
 * - String values containing backslash escapes: the scalar emits
 *   the raw escaped bytes; yyjson emits unescaped text. The
 *   generator never produces escapes (scalar's stated data
 *   assumption), so generator data is byte-identical.
 * - Integers > INT64_MAX: the scalar's strtoll clamps to LLONG_MAX
 *   (errno ignored); mirrored here explicitly. Generator values
 *   never approach the range.
 * - Duplicate keys: both this and the scalar take the FIRST
 *   occurrence (verified against the vendored yyjson).
 * - Trailing garbage after a valid object: the scalar structural
 *   gate accepts it (rooted==1) and emits; yyjson rejects the line.
 *   The generator never produces this shape (verified: all five
 *   malformed shapes converge), so equality holds on generator data.
 *   (An all-skip batch emits no record in either plugin, so batch
 *   counts can differ only on such off-schema inputs.)
 * - Verbatim rating span: searched whole-line here vs inside
 *   item_context in the scalar. The generator never emits a
 *   top-level "rating" key, so the two agree on all generator
 *   shapes (verified by the equality check).
 *
 * Build: gcc -O3 -shared -fPIC -march=native -I<repo>/ring_loadables
 *        -o ml_plugin_yyjson.so ml_plugin_yyjson.c yyjson.c -lm
 */

#include "forkrun_plugin.h"
#include "yyjson.h"

#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Dialect 2 + RAW borrowed window (reserved[0]). */
int forkrun_use_ctx = (int)(FORKRUN_CTX_ENABLE | FORKRUN_CTX_FLAG_RAW);

#define BASE_TS 1700000000LL

/* Per-record yyjson stack pool (values + unescaped strings for one
 * medium record total ~1KB; 16KB is 16x headroom). Re-initialized
 * per record (a few stores); records that still overflow fall back
 * to a heap-backed parse so no input is ever refused. */
#define YYJSON_POOL_SIZE (16 * 1024)

/* Growable static output buffer (single-threaded worker reuse). */
static char *g_out = NULL;
static size_t g_out_cap = 0;

/* Skip ASCII spaces. */
static const char *skip_ws(const char *p, const char *end) {
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r'))
        p++;
    return p;
}

/* Raw value span for VERBATIM float fields (scroll_depth, rating).
 * Byte-identical matching/spanning rules to the scalar find_field:
 * first textual "key" occurrence, string-aware quote handling,
 * brace-balanced {}[] spans, scalars run to ,}] with rtrim.
 * Verbatim slices preserve the generator's exact float text (no
 * float round-trip throughprintf/scanf, which would risk byte
 * drift on shortest-repr edge cases). */
static int raw_span(const char *obj, const char *end, const char *key,
                    const char **sp, size_t *np, int *is_strp) {
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
                *sp = s;
                *np = (size_t)(q - s);
                *is_strp = 1;
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
                *sp = v;
                *np = (size_t)(q - v);
                *is_strp = 0;
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
                *sp = v;
                *np = (size_t)(r - v);
                *is_strp = 0;
                return (r > v) ? 0 : -1;
            }
        }
        p++;
    }
    return -1;
}

/* ─── MlFields: single-pass extraction target ────────────────────
 *
 * W-PY32: one yyjson_obj_foreach pass visits each key exactly once
 * (~15 comparisons/record) instead of 10+ obj_get linear scans
 * (~150 comparisons). Length + first-character prefilter, full
 * memcmp confirmation (no character-index guesswork on
 * same-length collisions: user/item_context, price_cents/
 * num_reviews). First occurrence wins (scalar parity for duplicate
 * keys — enforced by seen bits, since generator dicts can't emit
 * duplicates but hand-fed inputs can).
 *
 * Validation semantics mirror the scalar exactly:
 * - strings: NULL = missing-or-wrong-type (required fields skip on
 *   NULL; optional tier defaults to 0).
 * - ts: ts_ok required (missing/invalid both skip).
 * - dur: tri-state (absent -> 0 -> filtered; valid -> value;
 *   present-invalid -> skip).
 * - rev/sess/dss/price: missing-or-invalid -> 0 (identical). */

typedef struct {
    const char *eid;
    size_t eid_n;
    const char *uid;
    size_t uid_n;
    const char *iid;
    size_t iid_n;
    const char *et;
    size_t et_n;
    const char *dev;
    size_t dev_n;
    const char *tier;
    size_t tier_n;
    long long ts_v;
    int ts_ok;
    long long dur_v;
    int dur_state; /* 0 absent, 1 valid, 2 present-invalid */
    long long rev_v;
    long long sess_v;
    long long dss_v;
    long long pr_v;
    uint32_t seen;
} ml_fields_t;

#define F_SEEN_EID  (1u << 0)
#define F_SEEN_UID  (1u << 1)
#define F_SEEN_IID  (1u << 2)
#define F_SEEN_ET   (1u << 3)
#define F_SEEN_DEV  (1u << 4)
#define F_SEEN_TS   (1u << 5)
#define F_SEEN_DUR  (1u << 6)
#define F_SEEN_REV  (1u << 7)
#define F_SEEN_TIER (1u << 8)
#define F_SEEN_SESS (1u << 9)
#define F_SEEN_DSS  (1u << 10)
#define F_SEEN_PR   (1u << 11)

/* Strict int64 with strtoll-clamp semantics (scalar parse_int):
 * SINT direct; UINT clamped at INT64_MAX; anything else invalid. */
static inline int strict_i64(yyjson_val *v, long long *dst) {
    uint64_t u;

    if (yyjson_is_sint(v)) {
        *dst = (long long)yyjson_get_sint(v);
        return 0;
    }
    if (yyjson_is_uint(v)) {
        u = yyjson_get_uint(v);
        *dst = (u > (uint64_t)INT64_MAX) ? INT64_MAX : (long long)u;
        return 0;
    }
    return -1;
}

static inline void ml_nested_user(yyjson_val *obj, ml_fields_t *f) {
    yyjson_val *key, *val;
    size_t nidx, nmax;

    yyjson_obj_foreach(obj, nidx, nmax, key, val) {
        const char *k = yyjson_get_str(key);
        size_t k_len = yyjson_get_len(key);

        if (k_len == 9 && k[0] == 'u' &&
            memcmp(k, "user_tier", 9) == 0) {
            if (!(f->seen & F_SEEN_TIER)) {
                f->seen |= F_SEEN_TIER;
                if (yyjson_is_str(val)) {
                    f->tier = yyjson_get_str(val);
                    f->tier_n = yyjson_get_len(val);
                }
            }
        } else if (k_len == 17 && k[0] == 'n' &&
                   memcmp(k, "num_prev_sessions", 17) == 0) {
            if (!(f->seen & F_SEEN_SESS)) {
                long long tmp;
                f->seen |= F_SEEN_SESS;
                if (strict_i64(val, &tmp) == 0)
                    f->sess_v = tmp;
            }
        } else if (k_len == 17 && k[0] == 'd' &&
                   memcmp(k, "days_since_signup", 17) == 0) {
            if (!(f->seen & F_SEEN_DSS)) {
                long long tmp;
                f->seen |= F_SEEN_DSS;
                if (strict_i64(val, &tmp) == 0)
                    f->dss_v = tmp;
            }
        }
        /* avg_session_duration_s (22) and anything else: ignored. */
    }
}

static inline void ml_nested_item(yyjson_val *obj, ml_fields_t *f) {
    yyjson_val *key, *val;
    size_t nidx, nmax;

    yyjson_obj_foreach(obj, nidx, nmax, key, val) {
        const char *k = yyjson_get_str(key);
        size_t k_len = yyjson_get_len(key);

        /* 11-char collision resolved by first char + memcmp:
         * price_cents ('p', extracted) vs num_reviews ('n'). */
        if (k_len == 11 && k[0] == 'p' &&
            memcmp(k, "price_cents", 11) == 0) {
            if (!(f->seen & F_SEEN_PR)) {
                long long tmp;
                f->seen |= F_SEEN_PR;
                if (strict_i64(val, &tmp) == 0)
                    f->pr_v = tmp;
            }
        }
        /* rating (6), category (8): handled via whole-line raw_span
         * (verbatim) / ignored respectively — not extracted here. */
    }
}

static inline void ml_fields_extract(yyjson_val *root, ml_fields_t *f) {
    yyjson_val *key, *val;
    size_t fidx, fmax;

    memset(f, 0, sizeof(*f));
    yyjson_obj_foreach(root, fidx, fmax, key, val) {
        const char *k = yyjson_get_str(key);
        size_t k_len = yyjson_get_len(key);

        switch (k_len) {
        case 6: /* "device" */
            if (k[0] == 'd' && memcmp(k, "device", 6) == 0 &&
                !(f->seen & F_SEEN_DEV)) {
                f->seen |= F_SEEN_DEV;
                if (yyjson_is_str(val)) {
                    f->dev = yyjson_get_str(val);
                    f->dev_n = yyjson_get_len(val);
                }
            }
            break;
        case 7: /* "user_id" / "item_id" */
            if (k[0] == 'u' && memcmp(k, "user_id", 7) == 0 &&
                !(f->seen & F_SEEN_UID)) {
                f->seen |= F_SEEN_UID;
                if (yyjson_is_str(val)) {
                    f->uid = yyjson_get_str(val);
                    f->uid_n = yyjson_get_len(val);
                }
            } else if (k[0] == 'i' && memcmp(k, "item_id", 7) == 0 &&
                       !(f->seen & F_SEEN_IID)) {
                f->seen |= F_SEEN_IID;
                if (yyjson_is_str(val)) {
                    f->iid = yyjson_get_str(val);
                    f->iid_n = yyjson_get_len(val);
                }
            }
            break;
        case 8: /* "event_id" */
            if (k[0] == 'e' && memcmp(k, "event_id", 8) == 0 &&
                !(f->seen & F_SEEN_EID)) {
                f->seen |= F_SEEN_EID;
                if (yyjson_is_str(val)) {
                    f->eid = yyjson_get_str(val);
                    f->eid_n = yyjson_get_len(val);
                }
            }
            break;
        case 9: /* "timestamp" */
            if (k[0] == 't' && memcmp(k, "timestamp", 9) == 0 &&
                !(f->seen & F_SEEN_TS)) {
                long long tmp;
                f->seen |= F_SEEN_TS;
                if (strict_i64(val, &tmp) == 0) {
                    f->ts_v = tmp;
                    f->ts_ok = 1;
                }
            }
            break;
        case 10: /* "event_type" (session_id ignored) */
            if (k[0] == 'e' && memcmp(k, "event_type", 10) == 0 &&
                !(f->seen & F_SEEN_ET)) {
                f->seen |= F_SEEN_ET;
                if (yyjson_is_str(val)) {
                    f->et = yyjson_get_str(val);
                    f->et_n = yyjson_get_len(val);
                }
            }
            break;
        case 11: /* "duration_ms" (nested price_cents lives inside
                  * item_context — a top-level 11-char key is not one
                  * of ours unless it memcmps). */
            if (k[0] == 'd' && memcmp(k, "duration_ms", 11) == 0 &&
                !(f->seen & F_SEEN_DUR)) {
                long long tmp;
                f->seen |= F_SEEN_DUR;
                if (strict_i64(val, &tmp) == 0) {
                    f->dur_v = tmp;
                    f->dur_state = 1;
                } else {
                    f->dur_state = 2;
                }
            }
            break;
        case 12: /* "user_context" / "item_context" (scroll_depth
                  * handled via whole-line raw_span, not here). */
            if (k[0] == 'u' && memcmp(k, "user_context", 12) == 0) {
                if (yyjson_is_obj(val))
                    ml_nested_user(val, f);
            } else if (k[0] == 'i' &&
                       memcmp(k, "item_context", 12) == 0) {
                if (yyjson_is_obj(val))
                    ml_nested_item(val, f);
            }
            break;
        case 13: /* "revenue_cents" */
            if (k[0] == 'r' && memcmp(k, "revenue_cents", 13) == 0 &&
                !(f->seen & F_SEEN_REV)) {
                long long tmp;
                f->seen |= F_SEEN_REV;
                if (strict_i64(val, &tmp) == 0)
                    f->rev_v = tmp;
            }
            break;
        default:
            break; /* session_id, experiment_bucket, category etc. */
        }
    }
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

static int encode_tier(const char *s, size_t n) {
    if (n == 4 && memcmp(s, "free", 4) == 0)
        return 0;
    if (n == 5 && memcmp(s, "basic", 5) == 0)
        return 1;
    if (n == 7 && memcmp(s, "premium", 7) == 0)
        return 2;
    return 0; /* Python default "free" -> 0 */
}

/* round-half-away to 4 decimals, shortest-ish print ("4.5", not
 * "4.5000"; "0.0", not "0").
 *
 * W-PY32: snprintf-free fast path with byte-identical output
 * (verified by a 3.6M-value differential sweep vs the snprintf
 * version above — zero mismatches, incl. negatives, zero, halfway
 * cases, ts_n/log ranges and fuzz). Integer digit extraction with
 * the identical trim rules; the snprintf fallback only serves
 * inf/nan/huge inputs that never occur in generator data. */
static void fmt_r4(double v, char *buf, size_t cap) {
    double r = round(v * 10000.0) / 10000.0;
    int neg = (r < 0.0) || (r == 0.0 && 1.0 / r < 0.0);
    double a = neg ? -r : r;
    double s = a * 10000.0 + 0.5;
    uint64_t scaled;
    uint64_t int_part;
    uint32_t frac;
    char *o = buf;
    size_t rem = cap;
    char *num;
    char itmp[24];
    int n = 0;

    if (!(s < 4503599627370496.0)) { /* inf/nan/huge fallback */
        char tmp[64];
        size_t e;

        snprintf(tmp, sizeof(tmp), "%.4f", r);
        e = strlen(tmp);
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
        return;
    }
    scaled = (uint64_t)s;
    num = o; /* digit start (after any sign) for the trim */
    if (neg) {
        if (rem < 2)
            return;
        *o++ = '-';
        rem--;
        num = o;
    }
    if (scaled == 0) {
        if (rem < 4)
            return;
        memcpy(o, "0.0", 3);
        o[3] = '\0';
        return;
    }
    int_part = scaled / 10000;
    frac = (uint32_t)(scaled % 10000);
    if (int_part == 0) {
        if (rem < 2)
            return;
        *o++ = '0';
        rem--;
    } else {
        while (int_part > 0) {
            itmp[n++] = (char)('0' + int_part % 10);
            int_part /= 10;
        }
        if ((size_t)n + 6 > rem)
            return;
        while (n > 0) {
            *o++ = itmp[--n];
            rem--;
        }
    }
    if (rem < 7)
        return;
    *o++ = '.';
    *o++ = (char)('0' + (frac / 1000) % 10);
    *o++ = (char)('0' + (frac / 100) % 10);
    *o++ = (char)('0' + (frac / 10) % 10);
    *o++ = (char)('0' + frac % 10);
    *o = '\0';
    {
        char *e = num + strlen(num);
        while (e > num && e[-1] == '0')
            e--;
        if (e > num && e[-1] == '.')
            e--;
        *e = '\0';
        if (strchr(num, '.') == NULL) {
            size_t l = strlen(num);
            num[l] = '.';
            num[l + 1] = '0';
            num[l + 2] = '\0';
        }
    }
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

/* One record; returns bytes appended, -1 to skip the line, -2 on
 * buffer overrun. Validation semantics mirror emit_medium exactly;
 * field lookup is a single foreach pass (see ml_fields_extract). */
static long emit_medium_yyjson(const char *line, const char *lend,
                               char **dst, size_t *left) {
    char pool_buf[YYJSON_POOL_SIZE];
    yyjson_alc alc;
    yyjson_doc *doc;
    yyjson_val *root;
    ml_fields_t f;
    int et_c, dev_c, tier_c = 0;
    long long rev_v = 0;
    char *o = *dst;
    size_t rem = *left;
    int w;
    char num1[32], num2[32];
    const char *scr_p;
    size_t scr_n;
    int scr_is_str;
    const char *rate_p;
    size_t rate_n;
    int rate_is_str;
    char scr_b[64], rate_b[64];
    size_t sn, rn;

    /* yyjson rejects malformed/truncated/garbage/empty spans (NULL)
     * exactly where the scalar structural gate rejects. The trimmed
     * span is never empty here (caller skips blanks). NO INSITU:
     * the input window is borrowed shared memory (read-only). */
    yyjson_alc_pool_init(&alc, pool_buf, sizeof(pool_buf));
    doc = yyjson_read_opts((char *)line, (size_t)(lend - line),
                           YYJSON_READ_NOFLAG, &alc, NULL);
    if (!doc) {
        /* Pool overflow on a huge record (or genuinely malformed):
         * retry heap-backed so no input size is ever refused. A
         * still-NULL doc is malformed -> skip the line. */
        doc = yyjson_read_opts((char *)line, (size_t)(lend - line),
                               YYJSON_READ_NOFLAG, NULL, NULL);
        if (!doc)
            return -1;
    }
    root = yyjson_doc_get_root(doc);
    if (!root || !yyjson_is_obj(root)) {
        yyjson_doc_free(doc);
        return -1;
    }
    ml_fields_extract(root, &f);

    /* Required top-level fields (missing/wrong-type -> skip). */
    if (!f.eid)
        goto skip;
    if (!f.uid)
        goto skip;
    if (!f.iid)
        goto skip;
    if (!f.ts_ok)
        goto skip;
    if (!f.et)
        goto skip;
    et_c = encode_event(f.et, f.et_n);
    if (et_c < 0)
        goto skip;
    if (!f.dev)
        goto skip;
    dev_c = encode_device(f.dev, f.dev_n); /* unknown -> -1 (parity) */
    /* duration_ms absent -> default 0 -> filtered (Python parity);
     * present-but-unparseable -> skip (wrong-type fails closed). */
    if (f.dur_state == 2)
        goto skip;
    if (f.dur_v < 100)
        goto skip;

    /* tier absent/wrong-type -> 0 (encode_tier defaults); sess/dss/
     * price already defaulted at extraction. */
    if (f.tier)
        tier_c = encode_tier(f.tier, f.tier_n);

    /* Format: computed doubles + verbatim pass-throughs. */
    {
        double ts_n = ((double)f.ts_v - (double)BASE_TS) / 86400.0;
        long long hod = (f.ts_v % 86400) / 3600;
        long long dow = (f.ts_v / 86400) % 7;
        char ts_nb[32], ld_b[32], lp_b[32];

        snprintf(ts_nb, sizeof(ts_nb), "%.15g", ts_n);
        fmt_r4(log1p((double)f.dur_v), ld_b, sizeof(ld_b));
        fmt_r4(log1p((double)f.pr_v), lp_b, sizeof(lp_b));
        /* Verbatim float slices (exact, like Python passthrough):
         * non-string spans copied raw; anything else -> "0.0". */
        sn = 0;
        if (raw_span(line, lend, "scroll_depth", &scr_p, &scr_n,
                     &scr_is_str) == 0 && !scr_is_str && scr_n > 0 &&
            scr_n < sizeof(scr_b)) {
            memcpy(scr_b, scr_p, scr_n);
            sn = scr_n;
        } else {
            memcpy(scr_b, "0.0", 3);
            sn = 3;
        }
        rn = 0;
        if (raw_span(line, lend, "rating", &rate_p, &rate_n,
                     &rate_is_str) == 0 && !rate_is_str && rate_n > 0 &&
            rate_n < sizeof(rate_b)) {
            memcpy(rate_b, rate_p, rate_n);
            rn = rate_n;
        } else {
            memcpy(rate_b, "0.0", 3);
            rn = 3;
        }
        /* rev: strict int > 0 -> 1, else 0 (missing/unparseable 0). */
        if (f.rev_v > 0)
            rev_v = 1;
        snprintf(num1, sizeof(num1), "%lld", hod);
        snprintf(num2, sizeof(num2), "%lld", dow);
        w = snprintf(o, rem,
                     "{\"eid\":\"%.*s\",\"uid\":\"%.*s\","
                     "\"iid\":\"%.*s\",\"ts_n\":%s,"
                     "\"hod\":%s,\"dow\":%s,\"et\":%d,"
                     "\"dev\":%d,\"log_dur\":%s,"
                     "\"scr\":%.*s,\"rev\":%lld,"
                     "\"tier\":%d,\"sess\":%lld,"
                     "\"dss\":%lld,\"log_pr\":%s,"
                     "\"rate\":%.*s}",
                     (int)f.eid_n, f.eid,
                     (int)f.uid_n, f.uid,
                     (int)f.iid_n, f.iid, ts_nb,
                     num1, num2, et_c, dev_c, ld_b,
                     (int)sn, scr_b, rev_v,
                     tier_c, f.sess_v, f.dss_v, lp_b,
                     (int)rn, rate_b);
    }
    yyjson_doc_free(doc);
    if (w < 0 || (size_t)w >= rem)
        return -2; /* buffer overrun: caller grows and retries */
    *dst = o + w;
    *left = rem - (size_t)w;
    return w;

skip:
    yyjson_doc_free(doc);
    return -1;
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
            /* Separator first; retracted when the line skips. */
            if (nrec > 0) {
                if (left < 1)
                    return -2;
                *o++ = '\n';
                left--;
            }
            r = emit_medium_yyjson(ls, le, &o, &left);
            if (r == -2)
                return -2;
            if (r >= 0) {
                nrec++;
            } else if (r == -1) {
                if (nrec > 0) {
                    o--;
                    left++;
                }
            } else {
                return -1;
            }
        }
        p = nl ? nl + 1 : end;
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
int ml_process_medium_yyjson(int argc, char **argv,
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
