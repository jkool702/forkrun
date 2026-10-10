/* fr_udf_helper -- PROTOTYPE, Phase 1 of DECISION-01 implementation.
 *
 * Purpose: establish the startup/runtime contract from DECISION-01 section
 * 6.1 BEFORE any launcher integration. Specifically, prove that an embedded
 * interpreter can be configured so that:
 *
 *   (a) it is isolated -- the caller's PYTHONPATH/user-site cannot reach it;
 *   (b) the user's INSTALLED packages remain importable, because a UDF that
 *       cannot import its own dependencies is useless;
 *   (c) the module search path is explicit and validated rather than
 *       inherited;
 *   (d) a UDF module and callable can be resolved, invoked, and its result
 *       converted to bytes.
 *
 * Deliberately NOT in this file yet: anything that touches the engine, forks
 * workers, or is wired into forkrun_cleanroom.c. This is a standalone probe
 * whose only job is to answer the questions above with evidence.
 *
 * Built against the LOCAL interpreter's headers and the FULL API (Option C as
 * the development mechanism, per DECISION-01 section 6.3). It is not the
 * shipped artifact.
 */

#define _GNU_SOURCE
#include <Python.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* ------------------------------------------------------------------------ */
/* 6.1 -- deliberate, explicit initialisation.                              */
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
        fprintf(stderr, "helper: cannot decode root %s\n", root);
        return -1;
    }
    PyStatus st = PyWideStringList_Append(&cfg->module_search_paths, w);
    PyMem_RawFree(w);
    if (PyStatus_Exception(st)) {
        fprintf(stderr, "helper: root rejected %s (exitcode %d)\n",
                root, st.exitcode);
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
            fprintf(stderr, "helper: program_name rejected\n");
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
        fprintf(stderr, "helper: sys.path is not a list\n");
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
/* Assertion helpers -- the contract is verified, not assumed.             */
/* ------------------------------------------------------------------------ */

/* Read sys.flags.<name> defensively.
 *
 * PyObject_GetAttrString returns NULL for a missing attribute, and
 * PyLong_AsLong(NULL) segfaults. Flag NAMES vary across minors -- this
 * prototype is the thing that discovers which -- so an absent flag is a
 * RESULT to report, not a crash. Returns -2 when the attribute is absent,
 * -1 on a real error, else the value. */
static long sysflag(const char *name, int *absent)
{
    *absent = 0;
    PyObject *sys = PyImport_ImportModule("sys");
    if (!sys) { PyErr_Print(); return -1; }
    PyObject *flags = PyObject_GetAttrString(sys, "flags");
    Py_DECREF(sys);
    if (!flags) { PyErr_Print(); return -1; }
    PyObject *v = PyObject_GetAttrString(flags, name);
    Py_DECREF(flags);
    if (!v) {
        if (PyErr_ExceptionMatches(PyExc_AttributeError)) {
            PyErr_Clear();
            *absent = 1;
            return -2;
        }
        PyErr_Print();
        return -1;
    }
    long got = PyLong_AsLong(v);
    Py_DECREF(v);
    return got;
}

static int flag_is(const char *name, long want)
{
    int absent = 0;
    long got = sysflag(name, &absent);
    if (absent) return -1;          /* cannot assert; caller must notice */
    if (got < 0) return -1;
    return got == want ? 0 : 1;
}

static void report_flags(void)
{
    static const char *names[] = {"isolated", "use_environment",
                                  "site_import", "user_site",
                                  "safe_path", "dont_write_bytecode",
                                  "no_site", "verbose", NULL};
    for (int i = 0; names[i]; i++) {
        int absent = 0;
        long v = sysflag(names[i], &absent);
        if (absent) printf("    sys.flags.%-20s = <absent>\n", names[i]);
        else if (v < 0) printf("    sys.flags.%-20s = <error>\n", names[i]);
        else printf("    sys.flags.%-20s = %ld\n", names[i], v);
    }
}

static void report_syspath(void)
{
    PyObject *sys = PyImport_ImportModule("sys");
    PyObject *p = PyObject_GetAttrString(sys, "path");
    Py_ssize_t n = PyList_Size(p);
    printf("    sys.path (%zd entries):\n", n);
    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *e = PyList_GetItem(p, i);
        printf("      [%zd] %s\n", i, PyUnicode_AsUTF8(e));
    }
}

/* Import a module by name, reporting rather than aborting -- a failed import
 * is data for this prototype, not a crash. */
static int try_import(const char *mod)
{
    PyObject *m = PyImport_ImportModule(mod);
    if (m) {
        printf("    import %-14s -> OK\n", mod);
        Py_DECREF(m);
        return 0;
    }
    /* Report WHY. A bare "NOT importable" made this prototype useless for
     * an hour: the root was correct, the module was present, and the real
     * cause was a transitive dependency in a different root entirely. */
    PyObject *t, *v, *tb;
    PyErr_Fetch(&t, &v, &tb);
    PyErr_NormalizeException(&t, &v, &tb);
    PyObject *r = PyObject_Repr(v);
    printf("    import %-14s -> %s\n", mod,
           r ? PyUnicode_AsUTF8(r) : "?");
    Py_XDECREF(r); Py_XDECREF(t); Py_XDECREF(v); Py_XDECREF(tb);
    PyErr_Clear();
    return 1;
}

/* ------------------------------------------------------------------------ */

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

    printf("== fr_udf_helper prototype ==\n");
    printf("  local interpreter : %s\n", PY_VERSION);
    printf("  import roots (%d)  :\n", nroots);
    for (int i = 0; i < nroots; i++) printf("      %s\n", roots[i]);
    if (!nroots) printf("      (none -- stdlib only)\n");
    fflush(stdout);

    /* VALIDATION, before the interpreter sees anything. An unvalidated root
     * is the thing we promised not to inherit. */
    for (int i = 0; i < nroots; i++) {
        if (access(roots[i], R_OK) != 0) {
            fprintf(stderr, "helper: root %s is not readable -- refusing\n",
                    roots[i]);
            return 2;
        }
    }

    PyConfig cfg;
    if (configure(&cfg) != 0)
        return 3;

    PyStatus st = Py_InitializeFromConfig(&cfg);
    PyConfig_Clear(&cfg);
    if (PyStatus_Exception(st)) {
        fprintf(stderr, "helper: Py_InitializeFromConfig failed "
                        "(exitcode %d)\n", st.exitcode);
        if (PyErr_Occurred()) PyErr_Print();
        return 4;
    }
    printf("  [ok] interpreter initialised\n");
    if (install_roots(roots, nroots) != 0) {
        fprintf(stderr, "helper: root installation failed\n");
        return 6;
    }
    printf("  [ok] %d validated root(s) installed into sys.path\n", nroots);
    fflush(stdout);

    printf("  -- flags --\n");        report_flags();
    printf("  -- path --\n");         report_syspath();
    fflush(stdout);

    /* (a) isolation actually holds. */
    int a_iso = flag_is("isolated", 1);
    int a_env = flag_is("use_environment", 0);
    printf("  -- (a) isolated=1        : %s\n",
           a_iso == 0 ? "HOLDS" : (a_iso < 0 ? "CANNOT CHECK" : "VIOLATED"));
    printf("  -- (a) use_environment=0: %s\n",
           a_env == 0 ? "HOLDS" : (a_env < 0 ? "CANNOT CHECK" : "VIOLATED"));
    fflush(stdout);

    /* (b)+(c) import behaviour. pytest is the probe for "user's installed
     * packages"; json/codecs are stdlib and must always work. */
    printf("  -- (b)/(c) imports --\n");
    try_import("json");              /* stdlib -- must always work */
    try_import("codecs");            /* stdlib -- must always work */
    /* A REAL package from the caller's user site. pytest is not installed
     * on every machine, so asserting on it would make this probe
     * environment-dependent and quietly vacuous. */
    try_import("numpy");                /* system site-packages */
    try_import("adjustText");           /* user site; imports numpy */
    fflush(stdout);

    /* (d) resolve and invoke a UDF. */
    if (udf_module && udf_attr) {
        printf("  -- (d) UDF %s:%s --\n", udf_module, udf_attr);
        PyObject *m = PyImport_ImportModule(udf_module);
        if (!m) {
            printf("    module import FAILED\n");
            PyErr_Print();
        } else {
            PyObject *fn = PyObject_GetAttrString(m, udf_attr);
            if (!fn) {
                printf("    attribute lookup FAILED\n");
                PyErr_Print();
            } else {
                /* Pass a bytes-like batch, matching the real UDF shape. */
                PyObject *arg = PyBytes_FromString("line000042\n");
                PyObject *res = PyObject_CallFunctionObjArgs(fn, arg, NULL);
                if (!res) {
                    printf("    call FAILED\n");
                    PyErr_Print();
                } else if (res == Py_None) {
                    /* The empty-batch case from DECISION-02. */
                    printf("    call -> None  (empty output; emits NO frame)\n");
                } else {
                    char *buf = NULL; Py_ssize_t n = 0;
                    if (PyBytes_AsStringAndSize(res, &buf, &n) == 0)
                        printf("    call -> bytes, %zd: %.*s\n", n,
                               (int)(n > 40 ? 40 : n), buf);
                    else {
                        printf("    call -> non-bytes (%s)\n",
                               Py_TYPE(res)->tp_name);
                        PyErr_Clear();
                    }
                }
                Py_XDECREF(arg); Py_XDECREF(fn);
            }
            Py_DECREF(m);
        }
        fflush(stdout);
    } else {
        printf("  -- (d) skipped: no udf module:attr given\n");
    }

    printf("  -- shutting down --\n"); fflush(stdout);
    if (Py_FinalizeEx() < 0) {
        fprintf(stderr, "helper: Py_FinalizeEx reported an error\n");
        return 5;
    }
    printf("  [ok] clean finalisation\n");
    return 0;
}
