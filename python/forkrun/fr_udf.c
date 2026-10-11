/* fr_udf.c -- embedded-CPython UDF helper, Phase 2 of DECISION-01.
 *
 * Implementation of fr_udf.h. The configuration logic here is the code
 * Phase 1 (fr_udf_helper.c) was written to discover; the comments
 * recording the dead ends are carried over deliberately, because they are
 * the reason the code looks the way it does and re-deriving them costs
 * hours. See DECISION-01 section 8, "Five things reading the API would not
 * have told me".
 *
 * The Phase-1 probe's main() still exists and still links against this
 * file, so the two cannot drift: if this implementation regresses the
 * probe's report changes too.
 */

#define _GNU_SOURCE
#include <Python.h>

#include "fr_udf.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int initialized = 0;
static char last_error[512] = "";

static void set_error(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(last_error, sizeof last_error, fmt, ap);
    va_end(ap);
}

/* ------------------------------------------------------------------------ */
/* DECISION-01 6.1 -- deliberate, explicit initialisation.                   */
/* ------------------------------------------------------------------------ */

/* Build the config. Nothing is left to defaults or to configuration files:
 * every path input is supplied by the caller and validated before it gets
 * here, because isolated=1 alone still lets configuration files supply the
 * path settings left unspecified.
 *
 * NOTE on a wrong turn worth recording: user_site_directory is an int
 * FLAG, not a path (cpython/initconfig.h:171). There is no field for "the
 * user site directory to use" -- it is on or off. So a caller who wants
 * user-installed packages importable must pass that root EXPLICITLY as a
 * module search path. That is the better shape anyway: an allowlist of
 * validated roots, never an inherited search path.
 *
 * Returns 0 on success. On failure the caller must NOT continue -- an
 * interpreter with an unvalidated search path is exactly the failure mode
 * this design exists to prevent.
 */
static int append_root(PyConfig *cfg, const char *root)
{
    wchar_t *w = Py_DecodeLocale(root, NULL);
    if (!w) {
        set_error("cannot decode root %s", root);
        return -1;
    }
    PyStatus st = PyWideStringList_Append(&cfg->module_search_paths, w);
    PyMem_RawFree(w);
    if (PyStatus_Exception(st)) {
        set_error("root rejected %s (exitcode %d)", root, st.exitcode);
        if (PyErr_Occurred()) PyErr_Print();
        return -1;
    }
    return 0;
}

static int configure(PyConfig *cfg)
{
    PyConfig_InitIsolatedConfig(cfg);

    /* Isolated config sets isolated=1 and use_environment=0, which is the
     * point: no PYTHONPATH, no PYTHONHOME, no user site. Assert rather than
     * assume, because the whole design rests on these. */
    cfg->isolated = 1;
    cfg->use_environment = 0;

    /* User site OFF (this is the int flag, not a path). */
    cfg->user_site_directory = 0;

    /* Site processing OFF. Consequence, which must not be glossed over:
     * third-party roots do NOT appear automatically. They are added
     * explicitly below. Leaving this on would re-admit .pth files and
     * sitecustomize -- code the caller did not ask to execute. */
    cfg->site_import = 0;

    /* safe_path: do not prepend the script's directory / cwd to sys.path.
     * Without it an interpreter can pick up modules from wherever it was
     * launched, which is inherited state by another name. */
    cfg->safe_path = 1;

    /* An explicit program name avoids the "prefix derived from argv[0]"
     * behaviour of a plain Py_Initialize, which is caller-influenced.
     *
     * MUST go through PyConfig_SetString, which copies. Assigning a string
     * LITERAL straight into cfg->program_name looks equivalent and is not:
     * PyConfig_Clear() frees that pointer, so the literal is free()d and the
     * process dies with "free(): invalid size". Cost one core dump to learn. */
    {
        PyStatus st = PyConfig_SetString(cfg, &cfg->program_name,
                                         L"forkrun-udf");
        if (PyStatus_Exception(st)) {
            set_error("program_name rejected");
            if (PyErr_Occurred()) PyErr_Print();
            return -1;
        }
    }

    /* DELIBERATELY not setting module_search_paths here. Two dead ends,
     * both found by running rather than reading, and both worth recording:
     *
     *  1. Appending to cfg->module_search_paths and leaving
     *     module_search_paths_set == 0: initialisation recomputes the
     *     search path from the prefix and DISCARDS the append. sys.path
     *     came back as three computed stdlib entries with our root
     *     silently gone -- a quiet failure, which is the worst kind.
     *
     *  2. Setting module_search_paths_set = 1 after appending: the flag
     *     means "this list is the COMPLETE search path", so the stdlib is
     *     dropped. Py_InitializeFromConfig then fails outright with
     *     "No module named 'encodings'" -- the interpreter cannot even
     *     start.
     *
     * So roots are added AFTER initialisation, by inserting into
     * sys.path. See install_roots(). No user code has run at that point,
     * so nothing has already been imported from the wrong place. */
    (void)append_root;   /* kept for the record; unused on this path */
    return 0;
}

/* Insert validated roots into sys.path AFTER initialisation.
 *
 * This is the only workable placement (see the two dead ends in configure).
 * Insertion order is reversed so the caller's roots appear in the order
 * given, with the caller's first root winning any shadowing contest. */
static int install_roots(const char *const *roots, int nroots)
{
    PyObject *path = PySys_GetObject("path");   /* borrowed */
    if (!path || !PyList_Check(path)) {
        set_error("sys.path is not a list");
        return -1;
    }
    for (int i = nroots - 1; i >= 0; i--) {
        if (!roots[i] || !*roots[i]) continue;
        PyObject *w = PyUnicode_DecodeFSDefault(roots[i]);
        if (!w) { PyErr_Print(); return -1; }
        if (PyList_Insert(path, 0, w) != 0) {
            Py_DECREF(w); PyErr_Print(); return -1;
        }
        Py_DECREF(w);
    }
    return 0;
}

/* ------------------------------------------------------------------------ */
/* Public API                                                                */
/* ------------------------------------------------------------------------ */

int fr_udf_init(const char *const *roots, int nroots)
{
    if (initialized) {
        /* Re-initialising a live interpreter is undefined. Fail loudly
         * rather than appear to succeed: the pre-fork candidate calls this
         * once in the parent, and a post-fork child must NOT call it
         * again. Silently returning OK here would turn a caller mistake
         * into undefined behaviour one crash later. */
        set_error("already initialized");
        return FR_UDF_ERR;
    }

    /* VALIDATION, before the interpreter sees anything. An unvalidated
     * root is the thing we promised not to inherit. */
    for (int i = 0; i < nroots; i++) {
        if (!roots[i] || !*roots[i]) continue;
        if (access(roots[i], R_OK) != 0) {
            set_error("root %s is not readable -- refusing", roots[i]);
            return FR_UDF_ERR;
        }
    }

    PyConfig cfg;
    if (configure(&cfg) != 0) {
        PyConfig_Clear(&cfg);
        return FR_UDF_ERR;
    }

    PyStatus st = Py_InitializeFromConfig(&cfg);
    PyConfig_Clear(&cfg);
    if (PyStatus_Exception(st)) {
        set_error("Py_InitializeFromConfig failed (exitcode %d)", st.exitcode);
        if (PyErr_Occurred()) PyErr_Print();
        return FR_UDF_ERR;
    }
    if (install_roots(roots, nroots) != 0) {
        Py_FinalizeEx();
        return FR_UDF_ERR;
    }
    initialized = 1;
    last_error[0] = '\0';
    return FR_UDF_OK;
}

int fr_udf_is_initialized(void) { return initialized; }

/* Cache the resolved callable. A UDF is called once per batch, so
 * re-importing per call would dominate the cost of small batches. */
static PyObject *cached_module = NULL;   /* borrowed-ish; strong ref */
static PyObject *cached_fn = NULL;       /* strong ref */
static char cached_spec[512];

static void clear_cache(void)
{
    Py_XDECREF(cached_fn);
    Py_XDECREF(cached_module);
    cached_fn = NULL;
    cached_module = NULL;
    cached_spec[0] = '\0';
}

int fr_udf_call(const char *module, const char *attr,
                const char *input, size_t len,
                char **out, size_t *out_len)
{
    if (!initialized) {
        set_error("not initialized");
        return FR_UDF_ERR;
    }
    if (!out || !out_len) {
        set_error("null out parameter");
        return FR_UDF_ERR;
    }
    *out = NULL;
    *out_len = 0;

    char spec[512];
    snprintf(spec, sizeof spec, "%s:%s", module ? module : "", attr ? attr : "");

    if (!cached_fn || strcmp(spec, cached_spec) != 0) {
        PyObject *m = PyImport_ImportModule(module);
        if (!m) {
            set_error("import of %s failed", module);
            PyErr_Print();
            return FR_UDF_ERR;
        }
        PyObject *fn = PyObject_GetAttrString(m, attr);
        if (!fn) {
            set_error("no attribute %s in %s", attr, module);
            PyErr_Print();
            Py_DECREF(m);
            return FR_UDF_ERR;
        }
        clear_cache();
        cached_module = m;      /* strong: keeps the module alive */
        cached_fn = fn;
        snprintf(cached_spec, sizeof cached_spec, "%s", spec);
    }

    PyObject *arg = PyBytes_FromStringAndSize(input ? input : "", (Py_ssize_t)len);
    if (!arg) { set_error("argument allocation failed"); PyErr_Print(); return FR_UDF_ERR; }
    PyObject *res = PyObject_CallFunctionObjArgs(cached_fn, arg, NULL);
    Py_DECREF(arg);
    if (!res) {
        set_error("call to %s raised", spec);
        PyErr_Print();
        return FR_UDF_ERR;
    }

    if (res == Py_None) {
        /* None: the UDF produced no result. Distinct from b"", and the
         * caller must be able to tell them apart -- see fr_udf.h. */
        Py_DECREF(res);
        return FR_UDF_NO_RESULT;
    }

    if (!PyBytes_Check(res)) {
        set_error("%s returned %s, not bytes", spec, Py_TYPE(res)->tp_name);
        PyErr_Clear();
        Py_DECREF(res);
        return FR_UDF_ERR;
    }

    char *buf = PyBytes_AsString(res);
    Py_ssize_t n = PyBytes_Size(res);
    if (n < 0) { set_error("size query failed"); Py_DECREF(res); return FR_UDF_ERR; }
    char *copy = (char *)malloc((size_t)n ? (size_t)n : 1);
    if (!copy) { set_error("out of memory"); Py_DECREF(res); return FR_UDF_ERR; }
    if (n) memcpy(copy, buf, (size_t)n);
    Py_DECREF(res);
    *out = copy;
    *out_len = (size_t)n;
    return FR_UDF_OK;
}

void fr_udf_free(char *buf) { free(buf); }

int fr_udf_finalize(void)
{
    if (!initialized) return FR_UDF_OK;
    clear_cache();
    int rc = FR_UDF_OK;
    if (Py_FinalizeEx() < 0) {
        set_error("Py_FinalizeEx reported an error");
        rc = FR_UDF_ERR;
    }
    initialized = 0;
    return rc;
}

int fr_udf_flag(const char *name)
{
    if (!initialized) return -1;
    PyObject *flags = PySys_GetObject("flags");    /* borrowed */
    if (!flags) return -1;
    PyObject *v = PyObject_GetAttrString(flags, name);
    if (!v) {
        PyErr_Clear();
        return -2;      /* absent on this minor -- a result, not a crash */
    }
    long lv = PyLong_AsLong(v);
    Py_DECREF(v);
    if (lv == -1 && PyErr_Occurred()) { PyErr_Clear(); return -1; }
    return (int)lv;
}

int fr_udf_import_ok(const char *module)
{
    if (!initialized) return -1;
    PyObject *m = PyImport_ImportModule(module);
    if (!m) {
        /* Do NOT swallow this silently: a bare "not importable" probe is
         * close to useless, because the usual cause is a transitive
         * dependency in a different root, not the root itself. */
        PyErr_Print();
        return 0;
    }
    Py_DECREF(m);
    return 1;
}

const char *fr_udf_last_error(void) { return last_error; }

const char *fr_udf_version(void) { return PY_VERSION; }

/* ------------------------------------------------------------------------ */
/* CPython fork lifecycle                                                   */
/* ------------------------------------------------------------------------ */

/* The hooks live behind CPython's own HAVE_FORK guard (intrcheck.h), so
 * on a build without fork support they do not exist at all. We do NOT
 * degrade them into no-ops: a caller that believes it choreographed its
 * forks when it did not is exactly the silent-corruption case these
 * functions exist to prevent. Fail closed instead, and let the caller ask
 * first with fr_udf_fork_hooks_available(). */
#if defined(HAVE_FORK)
#define FR_UDF_FORK_HOOKS 1
#else
#define FR_UDF_FORK_HOOKS 0
#endif

int fr_udf_fork_hooks_available(void) { return FR_UDF_FORK_HOOKS; }

int fr_udf_before_fork(void)
{
    if (!initialized) {
        set_error("before_fork: interpreter not initialized");
        return FR_UDF_ERR;
    }
#if FR_UDF_FORK_HOOKS
    /* Takes the import lock and marks other threads as blocked. Must be
     * paired with after_fork_parent on EVERY path out, including a
     * failed fork() -- hence the caller's obligation, not ours. */
    PyOS_BeforeFork();
    return FR_UDF_OK;
#else
    set_error("before_fork: CPython built without fork support");
    return FR_UDF_ERR;
#endif
}

int fr_udf_after_fork_parent(void)
{
    if (!initialized) {
        set_error("after_fork_parent: interpreter not initialized");
        return FR_UDF_ERR;
    }
#if FR_UDF_FORK_HOOKS
    PyOS_AfterFork_Parent();
    return FR_UDF_OK;
#else
    set_error("after_fork_parent: CPython built without fork support");
    return FR_UDF_ERR;
#endif
}

int fr_udf_after_fork_child(void)
{
    if (!initialized) {
        set_error("after_fork_child: interpreter not initialized");
        return FR_UDF_ERR;
    }
#if FR_UDF_FORK_HOOKS
    /* Reinitialises interpreter and thread state in the child. Must be
     * the FIRST thing the child does if it will touch Python again. */
    PyOS_AfterFork_Child();
    return FR_UDF_OK;
#else
    set_error("after_fork_child: CPython built without fork support");
    return FR_UDF_ERR;
#endif
}
