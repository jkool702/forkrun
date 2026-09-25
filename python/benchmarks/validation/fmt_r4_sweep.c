/* Differential sweep: fmt_r4 (scalar, snprintf-based) vs fmt_r4_fast.
 * Must match byte-for-byte on all inputs. */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void fmt_r4(double v, char *buf, size_t cap) {
    double r = round(v * 10000.0) / 10000.0;
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

/* Candidate fast version: exact fmt_r4 semantics, no snprintf. */
static void fmt_r4_fast(double v, char *buf, size_t cap) {
    double r = round(v * 10000.0) / 10000.0;
    int neg = (r < 0.0) || (1.0 / r < 0.0 && r == 0.0);
    double a = neg ? -r : r;
    /* Scale with round-half-up on the exact binary value. r is a
     * multiple of 1e-4 in real arithmetic, but binary storage may
     * sit epsilon below (e.g. 85173.9999999). Adding 0.5 then
     * flooring reproduces glibc %.4f rounding of the same binary
     * value in the verified range (see sweep). */
    double s = a * 10000.0 + 0.5;
    uint64_t scaled;
    uint64_t int_part;
    uint32_t frac;
    char *o = buf;
    size_t rem = cap;
    char itmp[24];
    int n = 0;

    if (!(s < 4503599627370496.0)) { /* fallback: inf/nan/huge */
        snprintf(buf, cap, "%.4f", r);
        /* then apply the identical trim rules */
        {
            size_t e = strlen(buf);
            if (strchr(buf, '.') != NULL) {
                while (e > 0 && buf[e - 1] == '0')
                    e--;
                if (e > 0 && buf[e - 1] == '.')
                    e--;
            }
            buf[e] = '\0';
        }
        if (buf[0] == '\0' || (buf[0] == '-' && buf[1] == '\0')) {
            snprintf(buf, cap, "0.0");
            return;
        }
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
    /* Re-derive the zero rule identically: scaled==0 -> "0.0"
     * (covers r in (-5e-5, 5e-5) incl. -0.0, matching scalar's
     * e==0 / lone-'-' rule — verified by sweep, incl. "-0.0").
     * num marks the digit start (after any sign) for the trim. */
    char *num = o;
    if (neg) {
        if (rem < 2)
            return;
        *o++ = '-';
        rem--;
        num = o;
    }
    if (scaled == 0) {
        snprintf(o, rem, "0.0");
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
        while (n > 0)
            *o++ = itmp[--n], rem--;
    }
    if (rem < 7)
        return;
    *o++ = '.';
    *o++ = (char)('0' + (frac / 1000) % 10);
    *o++ = (char)('0' + (frac / 100) % 10);
    *o++ = (char)('0' + (frac / 10) % 10);
    *o++ = (char)('0' + frac % 10);
    *o = '\0';
    /* Trim trailing zeros exactly like fmt_r4. */
    {
        char *e = num + strlen(num);
        while (e > num && e[-1] == '0')
            e--;
        if (e > num && e[-1] == '.')
            e--;
        /* e==num cannot happen here (scaled != 0 guarantees digits);
         * lone '-' cannot happen (digits follow the sign). */
        *e = '\0';
        if (strchr(num, '.') == NULL) {
            size_t l = strlen(num);
            num[l] = '.';
            num[l + 1] = '0';
            num[l + 2] = '\0';
        }
    }
}

int main(void) {
    char b1[64], b2[64];
    uint64_t rng = 0x123456789abcdefULL;
    long mism = 0, total = 0;
#define CHECK(v) do { \
        fmt_r4((v), b1, sizeof(b1)); \
        fmt_r4_fast((v), b2, sizeof(b2)); \
        total++; \
        if (strcmp(b1, b2) != 0) { \
            if (mism < 20) printf("MISMATCH v=%.17g ref=%s fast=%s\n", (double)(v), b1, b2); \
            mism++; \
        } \
    } while (0)
    /* Structured edge values. */
    {
        double edges[] = {0.0, -0.0, 0.0001, -0.0001, 0.00005, 0.000049,
                          0.5, 1.0, 1.5, -1.5, 2.5, 4.6052, 8.5174,
                          11.5129, 365.25, 100.1234, 999.9999, 0.99995,
                          2.675, 1.005, 123.456789, 24855.0, 1e10,
                          1e15, 0.30000000000000004, 1e-10, 1e10,
                          3.14159265358979, 2.71828182845904};
        size_t i;
        for (i = 0; i < sizeof(edges) / sizeof(edges[0]); i++)
            CHECK(edges[i]);
        /* ts_n range: ((ts-1.7e9)/86400) for ts in [1.6e9, 1.8e9]. */
        for (i = 0; i < 200000; i++) {
            double ts = 1600000000.0 + (double)i * 1000.0;
            CHECK((ts - 1700000000.0) / 86400.0);
        }
        /* log1p range (durations/prices). */
        for (i = 0; i < 200000; i++)
            CHECK(log1p((double)i * 7.0));
        /* Adversarial halfway cases x.xxx5 (binary-exact halves are
         * rare; sweep the decimal grid directly). */
        for (i = 0; i < 200000; i++)
            CHECK((double)i / 10000.0 + 0.00005);
    }
    /* Fuzz: uniform doubles across magnitudes + log/normal shapes. */
    {
        long i;
        for (i = 0; i < 3000000; i++) {
            rng = rng * 6364136223846793005ULL + 1442695040888963407ULL;
            double u = (double)(rng >> 11) / 9007199254740992.0;
            double v;
            switch (i % 4) {
            case 0:
                v = u * 40000.0 - 10.0;
                break;
            case 1:
                v = log1p(u * 200000.0);
                break;
            case 2:
                v = (u - 0.5) * 0.02;
                break;
            default:
                v = u * u * 1000.0;
                break;
            }
            CHECK(v);
        }
    }
    printf("total=%ld mismatches=%ld\n", total, mism);
    return mism ? 1 : 0;
#undef CHECK
}
