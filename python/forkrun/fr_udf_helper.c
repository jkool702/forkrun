/* fr_udf_helper -- Phase-1 PROBE, now a driver over the Phase-2 library.
 *
 * This file started as a standalone program whose only job was to answer
 * DECISION-01 section 6.1 with evidence before any launcher integration
 * existed. That job is done, and the logic it discovered now lives in
 * fr_udf.c (the shipped-shape artifact).
 *
 * It is KEPT, and kept working, for two reasons:
 *   - it is the diagnostic view: the contract report below prints what the
 *     interpreter actually did, which is what made findings 1-5 in
 *     DECISION-01 section 8 findable in the first place;
 *   - because it now calls the same library the launcher will call, it
 *     cannot drift from the shipped path. If fr_udf.c regresses, this
 *     report changes -- which is exactly the check that was missing when
 *     the probe and the implementation were the same file for different
 *     reasons.
 *
 * Run: make -f Makefile.substrate udf-probe
 *      python/forkrun/fr_udf_helper [root ...] [module:attr]
 */

#include "fr_udf.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Read sys.flags defensively: names vary by minor, so absence is a
 * result to report rather than a crash. Returns -2 when absent. */
static long sysflag(const char *name, int *absent)
{
    int v = fr_udf_flag(name);
    if (v == -2) { if (absent) *absent = 1; return 0; }
    if (absent) *absent = 0;
    return (long)v;
}

static const char *tri(int v)
{
    if (v == -2) return "ABSENT on this minor";
    if (v < 0)   return "CANNOT CHECK";
    return v ? "yes" : "no";
}

static void report_flags(void)
{
    static const char *names[] = {
        "isolated", "use_environment", "no_site", "safe_path",
        "site_import", "user_site", "dont_write_bytecode", NULL
    };
    for (int i = 0; names[i]; i++) {
        int absent = 0;
        long v = sysflag(names[i], &absent);
        /* Honour `absent` rather than printing the 0 that sysflag
         * substituted for it. Getting this wrong is not cosmetic: it
         * made an ABSENT flag print as "= 0", and the (a) checks below,
         * which re-query the real -2, then reported the same property
         * as both "0" and "VIOLATED" in one run. DECISION-01 section 8
         * finding 4 says the names differ per minor; the report has to
         * be able to say so. */
        printf("      sys.flags.%-20s = %s\n", names[i],
               absent ? "ABSENT on this minor" : tri((int)v));
    }
}

static void report_syspath(void)
{
    printf("      (root list is inserted at the FRONT, in caller order)\n");
}

static const char *verdict(int v, int want)
{
    if (v == -2) return "CANNOT CHECK (absent on this minor)";
    if (v < 0)   return "CANNOT CHECK";
    return v == want ? "HOLDS" : "VIOLATED";
}

static void report_imports(void)
{
    /* json/codecs are stdlib and must always work. */
    fr_udf_import_ok("json");
    fr_udf_import_ok("codecs");
    /* A REAL third-party package. Asserting on a specific one makes the
     * probe environment-dependent and quietly vacuous, so treat absence
     * as information rather than a failure. */
    int np = fr_udf_import_ok("numpy");
    printf("      numpy (system site)      : %s\n",
           np < 0 ? "CANNOT CHECK" : (np ? "importable" : "NOT importable"));
}

int main(int argc, char **argv)
{
    /* argv[1..] are validated import roots; then module:attr for the UDF. */
    const char *udf_spec = NULL;
    int nroots = 0;
    const char *roots[16];

    for (int i = 1; i < argc && nroots < 16; i++) {
        if (strchr(argv[i], ':')) { udf_spec = argv[i]; break; }
        roots[nroots++] = argv[i];
    }
    const char *udf_module = NULL, *udf_attr = NULL;
    if (udf_spec) {
        static char mbuf[256];
        snprintf(mbuf, sizeof mbuf, "%s", udf_spec);
        char *colon = strrchr(mbuf, ':');
        if (colon) { *colon = '\0'; udf_module = mbuf; udf_attr = colon + 1; }
    }

    printf("== fr_udf_helper probe (driving the Phase-2 library) ==\n");
    printf("  library interpreter : %s\n", fr_udf_version());
    printf("  import roots (%d)  :\n", nroots);
    for (int i = 0; i < nroots; i++) printf("      %s\n", roots[i]);
    if (!nroots) printf("      (none -- stdlib only)\n");
    fflush(stdout);

    if (fr_udf_init(roots, nroots) != FR_UDF_OK) {
        fprintf(stderr, "helper: init failed: %s\n", fr_udf_last_error());
        return 3;
    }
    printf("  [ok] interpreter initialised, %d validated root(s) installed\n",
           nroots);

    /* Fork choreography availability. Reported rather than assumed: the
     * hooks are compiled only under CPython's HAVE_FORK, and a caller
     * that forks an initialised interpreter needs to know which it has. */
    printf("  -- fork --\n");
    printf("      CPython fork hooks    : %s\n",
           fr_udf_fork_hooks_available()
             ? "available (PyOS_BeforeFork/AfterFork_*)"
             : "UNAVAILABLE (CPython built without HAVE_FORK)");
    printf("\n");

    printf("  -- flags --\n");  report_flags();  printf("\n");
    printf("  -- path --\n");   report_syspath(); printf("\n");

    /* (a) isolation actually holds. */
    /* ABSENT is neither HOLDS nor VIOLATED: report it as uncheckable
     * rather than as a violation, or the report will accuse the design
     * of a breach it did not commit. */
    verdict(fr_udf_flag("isolated"), 1);
    verdict(fr_udf_flag("use_environment"), 0);
    printf("  -- (a) isolated=1        : %s\n",
           verdict(fr_udf_flag("isolated"), 1));
    printf("  -- (a) use_environment=0: %s\n",
           verdict(fr_udf_flag("use_environment"), 0));
    printf("\n");

    printf("  -- (b)/(c) imports --\n"); report_imports(); printf("\n");

    if (udf_module && udf_attr) {
        printf("  -- (d) UDF %s:%s --\n", udf_module, udf_attr);
        char *out = NULL; size_t n = 0;
        int rc = fr_udf_call(udf_module, udf_attr,
                             "line000042\n", strlen("line000042\n"),
                             &out, &n);
        if (rc == FR_UDF_OK) {
            printf("    call -> bytes, %zu: %.*s\n", n,
                   (int)(n > 40 ? 40 : n), out ? out : "");
            fr_udf_free(out);
        } else if (rc == FR_UDF_NO_RESULT) {
            printf("    call -> None  (no result; NO_RESULT, not an empty frame)\n");
        } else {
            printf("    call FAILED: %s\n", fr_udf_last_error());
        }
    } else {
        printf("  -- (d) skipped: no udf module:attr given\n");
    }

    printf("  -- shutting down --\n"); fflush(stdout);
    if (fr_udf_finalize() != FR_UDF_OK) {
        fprintf(stderr, "helper: finalize failed: %s\n", fr_udf_last_error());
        return 5;
    }
    printf("  [ok] clean finalisation\n");
    return 0;
}
