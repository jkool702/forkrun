/* Stage 0 forkrun side: calibrated per-record CPU burn (argv path).
 * Fixed args: --cost-us <C>. Burns ~C microseconds of float ops per record
 * (runtime-calibrated on first batch, cached), then re-emits the line.
 * Output contract: byte-identical to the consumed input.
 * Calibration mirrors the Python incumbents' per-process calibration;
 * the cost axis is nominal — the curve shape is the instrument. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define CAL_OPS 200000L

static double ops_per_us(void) {
    static double cached = 0.0;
    if (cached != 0.0) return cached;
    volatile double x = 1.000001;
    struct timespec a, b;
    clock_gettime(CLOCK_MONOTONIC, &a);
    for (long i = 0; i < CAL_OPS; i++) x = x * 1.000001 + 0.5;
    clock_gettime(CLOCK_MONOTONIC, &b);
    double us = (b.tv_sec - a.tv_sec) * 1e6 + (b.tv_nsec - a.tv_nsec) / 1e3;
    if (us < 1e-9) us = 1e-9;
    if (x == 0.0) cached = 1.0;
    else cached = CAL_OPS / us;
    return cached;
}

int transform_burn(int argc, char **argv) {
    double cost_us = 100.0;
    int first = 0;
    for (int i = 0; i + 1 < argc; i++) {
        if (strcmp(argv[i], "--cost-us") == 0) {
            cost_us = atof(argv[i + 1]);
            first = i + 2;
            break;
        }
    }
    long ops = (long)(ops_per_us() * cost_us);
    if (ops < 1) ops = 1;
    for (int i = first; i < argc; i++) {
        volatile double x = 1.000001;
        for (long k = 0; k < ops; k++) x = x * 1.000001 + 0.5;
        if (x == 0.0) return 1;
        size_t n = strlen(argv[i]);
        if (fwrite(argv[i], 1, n, stdout) != n) return 1;
        if (fputc('\n', stdout) != '\n') return 1;
    }
    return 0;
}
