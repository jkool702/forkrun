/* fr_udf.h -- embedded-CPython UDF helper, Phase 2 of DECISION-01.
 *
 * This is the shipped-shape artifact that Phase 1 (fr_udf_helper.c's
 * probe) was built to justify: a loadable per-minor shared object that
 * embeds a deliberately-initialised interpreter and calls a user UDF.
 *
 * Why a shared object and not a second executable: the launcher is
 * exec'd, so anything it must run has to be reachable from it. A .so
 * that is dlopen'd only in UDF mode keeps every non-UDF run exactly as
 * it was -- no libpython in the process, no DT_NEEDED change for the
 * ordinary path. That isolation of blast radius is the reason for the
 * .so rather than linking the interpreter into the launcher.
 *
 * Why per-minor rather than abi3: see DECISION-01 sections 2.1 and 7.
 * The configuration API used here is not in the Stable ABI, and the
 * Stable-ABI shared library is not present in every distribution.
 *
 * THREADING / FORK CONTRACT
 *   The interpreter is process-global. One fr_udf_init() per process.
 *   Initialising it in the parent BEFORE fork is the pre-fork candidate
 *   (C0.4); initialising in each child after fork is post-fork. Both are
 *   supported and measured -- see DECISION-01 section 9. A process that
 *   has initialised must not initialise twice; fr_udf_init() returns
 *   FR_UDF_ERR rather than re-initialising, because a second
 *   Py_InitializeFromConfig on a live interpreter is undefined.
 *
 *   Because CPython's runtime is not fork-safe in general, this is only
 *   safe when the forking process is single-threaded at the moment of
 *   the fork. That holds for the launcher (it forks before starting any
 *   worker threads) and is a precondition, not an accident.
 */
#ifndef FR_UDF_H
#define FR_UDF_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Call outcomes. NO_RESULT is a first-class answer, not an error: the UDF
 * returned None, which DECISION-02 requires to stay distinct from a real
 * empty result (b""). Conflating them is the bug this API exists to make
 * impossible -- so the caller gets a distinct code rather than a zero-length
 * buffer it has to guess about. */
enum {
    FR_UDF_OK        = 0,
    FR_UDF_NO_RESULT = 1,
    FR_UDF_ERR       = -1
};

/* Initialise the interpreter with an explicit, validated set of import
 * roots. Roots are checked for readability BEFORE the interpreter sees
 * them, then inserted into sys.path in the order given (first root wins).
 *
 * Derive the root set from the interpreter's own site.getsitepackages()
 * plus site.getusersitepackages(); never hardcode it. With site_import=0
 * (which is required for isolation) NO site root is added automatically,
 * not even the system one, so a UDF's transitive dependencies routinely
 * span roots. See DECISION-01 section 8, finding 1.
 *
 * Returns FR_UDF_OK, or FR_UDF_ERR (message available from
 * fr_udf_last_error). */
int fr_udf_init(const char *const *roots, int nroots);

/* Non-zero once the interpreter is up. */
int fr_udf_is_initialized(void);

/* Resolve module:attr and call it with a single bytes argument.
 *
 * On FR_UDF_OK, out/out_len receive a malloc'd buffer the caller MUST
 * release with fr_udf_free(). On FR_UDF_NO_RESULT, *out is NULL and
 * *out_len is 0 -- and that is deliberately distinguishable from a
 * successful zero-length result, which sets *out to a non-NULL pointer.
 *
 * The resolved callable is cached, so a repeated call on the same
 * module:attr skips re-import and re-attribute lookup. */
int fr_udf_call(const char *module, const char *attr,
                const char *input, size_t len,
                char **out, size_t *out_len);

/* Release a buffer from fr_udf_call. Tolerates NULL. */
void fr_udf_free(char *buf);

/* Shut the interpreter down. Returns FR_UDF_OK or FR_UDF_ERR. */
int fr_udf_finalize(void);

/* Diagnostics, used by the contract tests. These report rather than
 * assert: sys.flags attribute NAMES differ across minors (on 3.14,
 * site_import and user_site are absent while no_site and safe_path
 * exist), so absence is a result to surface, not a crash. */
int fr_udf_flag(const char *name);   /* -2 absent, -1 error, else value */
int fr_udf_import_ok(const char *module);
const char *fr_udf_last_error(void);
const char *fr_udf_version(void);

#ifdef __cplusplus
}
#endif

#endif /* FR_UDF_H */
