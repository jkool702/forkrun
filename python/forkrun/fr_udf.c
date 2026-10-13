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
#include <errno.h>
#include <limits.h>
#include <unistd.h>

static int initialized = 0;
static char last_error[512] = "";

/* Defined further down, next to the rest of the exception handling;
 * declared here because the config path below also reports through it. */
static void take_exception(char *buf, size_t bufsz, const char *prefix);

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
        if (PyErr_Occurred())
            take_exception(last_error, sizeof last_error, "root: ");
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
     * launched, which is inherited state by another name.
     *
     * PyConfig.safe_path landed in 3.11 (PEP 587); the field does not
     * exist in 3.10, and assigning to it there is a COMPILE ERROR. This
     * file's header claimed the helper "builds across the 3.10-3.15
     * target" and did not, for exactly this line -- found by the C0.5
     * interpreter matrix, which is the gate that exists to find
     * precisely this.
     *
     * Simply dropping the assignment on 3.10 would compile, but it
     * would also silently drop the SECURITY property, since that field
     * is what keeps a caller-influenced directory off sys.path. So 3.10
     * enforces the same rule by hand in enforce_path_policy(), called
     * after initialisation and before any user code can run. */
#if PY_VERSION_HEX >= 0x030B0000
    cfg->safe_path = 1;
#endif

    /* An explicit program name avoids the "prefix derived from argv[0]"
     * behaviour of a plain Py_Initialize, which is caller-influenced.
     *
     * MUST go through PyConfig_SetString, which copies. Assigning a string
     * LITERAL straight into cfg->program_name looks equivalent and is not:
     * PyConfig_Clear() frees that pointer, so the literal is free()d and the
     * process dies with "free(): invalid size". Cost one core dump to learn. */
    /* Relocated-interpreter support, added by the C0.5 matrix.
     *
     * program_name is set to a path-LESS literal just below. That makes
     * the interpreter search PATH for "forkrun-udf", fail, and fall back
     * to its COMPILED-IN prefix. For the system interpreter that is
     * /usr and everything works. For a relocated build it is wrong, and
     * initialisation dies with "No module named 'encodings'" before any
     * UDF runs -- which is exactly what the 3.10-3.15 matrix hit, since
     * those interpreters had to be unpacked outside /usr.
     *
     * FR_UDF_HOME names the prefix explicitly for that case. It is opt-in
     * and unset in normal operation, so the production path is unchanged.
     * Note this is a MEASUREMENT ENABLER, not a fix: the underlying
     * question -- whether the helper should support relocated
     * interpreters at all -- is a deployment decision, not a testing
     * one, and is recorded as open. */
    {
        const char *want_home = getenv("FR_UDF_HOME");
        if (want_home && *want_home) {
            /* PyConfig_SetString takes a wchar_t*, and getenv gives a
             * char*. Py_DecodeLocale is the documented bridge and does
             * the right thing for a non-ASCII prefix; handing it the
             * char* directly is only a -Wincompatible-pointer-types
             * warning that becomes memory corruption at run time. */
            wchar_t *w_home = Py_DecodeLocale(want_home, NULL);
            if (w_home == NULL) {
                set_error("home is not decodable in the locale encoding");
                take_exception(last_error, sizeof last_error, "home: ");
                return FR_UDF_ERR;
            }
            PyStatus st = PyConfig_SetString(cfg, &cfg->home, w_home);
            PyMem_RawFree(w_home);
            if (PyStatus_Exception(st)) {
                set_error("home rejected");
                take_exception(last_error, sizeof last_error, "home: ");
                return FR_UDF_ERR;
            }
        }
    }
    {
        PyStatus st = PyConfig_SetString(cfg, &cfg->program_name,
                                         L"forkrun-udf");
        if (PyStatus_Exception(st)) {
            set_error("program_name rejected");
            if (PyErr_Occurred())
                take_exception(last_error, sizeof last_error, "program_name: ");
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

/* Remove caller-influenced entries from sys.path.
 *
 * The 3.11+ equivalent is `cfg->safe_path = 1`, which tells the
 * interpreter not to prepend the script's directory or the cwd. On 3.10
 * that field does not exist, so the same rule is applied by hand here.
 *
 * Placement is load-bearing: this runs AFTER initialisation (so the
 * interpreter has built its sys.path) and BEFORE install_roots() and any
 * user payload, because the whole point is that no user code has run
 * while the inherited entries are still reachable.
 *
 * Only entries that are NOT interpreter-owned are removed -- the empty
 * string (which means "the current directory") and any entry equal to
 * the current working directory. Stdlib, lib-dynload and the site
 * directories are left alone: removing those would break imports, and
 * they are not caller-influenced.
 */
/* Resolve the current directory into a dynamically sized buffer.
 *
 * getcwd() with a fixed buffer fails with ERANGE when the path is longer
 * than the buffer. The previous version treated that failure as "no cwd
 * known", which silently disabled the comparison and left a literal-cwd
 * entry on sys.path while still reporting success -- the exact
 * fail-open behaviour a security boundary must not have.
 *
 * Returns 0 and sets *out to a malloc'd NUL-terminated string, or -1. */
static int resolve_cwd(char **out)
{
    size_t cap = 1024;
    for (int attempt = 0; attempt < 8; attempt++, cap *= 4) {
        char *buf = (char *)malloc(cap);
        if (!buf) return -1;
        if (getcwd(buf, cap) != NULL) {
            *out = buf;
            return 0;
        }
        free(buf);
        if (errno != ERANGE) return -1;   /* a real failure, not growth */
    }
    return -1;   /* never grew enough */
}

/* Is this sys.path entry a caller-influenced location?
 *
 * Compares against the current directory in TWO spellings: the literal
 * getcwd() result, and its realpath(). A symlinked or bind-mounted
 * working directory yields a different byte string for the same place,
 * and the review is right that byte-equality alone leaves that open.
 *
 * Returns 1 caller-influenced, 0 safe, -1 CANNOT DETERMINE.
 * -1 is a distinct outcome because the caller must fail closed on it:
 * a security boundary that answers "probably fine" when it cannot tell
 * is not a boundary. */
static int entry_is_caller_influenced(const char *c,
                                      const char *cwd,
                                      const char *cwd_real)
{
    if (c == NULL) return -1;                 /* not a string at all */
    if (c[0] == '\0') return 1;               /* '' means cwd */
    if (cwd && strcmp(c, cwd) == 0) return 1;
    if (cwd_real && strcmp(c, cwd_real) == 0) return 1;
    /* Trailing slashes: "/tmp/x" and "/tmp/x/" are the same directory. */
    if (cwd) {
        size_t n = strlen(cwd);
        if (strncmp(c, cwd, n) == 0 && (c[n] == '/' || c[n] == '\0'))
            return 1;
    }
    if (cwd_real) {
        size_t n = strlen(cwd_real);
        if (strncmp(c, cwd_real, n) == 0 && (c[n] == '/' || c[n] == '\0'))
            return 1;
    }
    return 0;
}

int fr_udf_classify_path_entry(const char *c)
{
    /* Test seam. The review's rule B ("path variants and adjacent
     * entries") cannot be driven through real initialisation -- CPython
     * decides what lands on sys.path -- so the CLASSIFIER is exposed
     * and tested directly for spellings the interpreter would not
     * produce on demand.
     *
     * This is deliberately NOT a way to establish the policy: only the
     * real fr_udf_init() path can do that. It covers the decision table,
     * and the policy tests cover the wiring. */
    char *cwd = NULL, *cwd_real = NULL;
    if (resolve_cwd(&cwd) != 0) return -1;
    char resolved[PATH_MAX];
    if (realpath(cwd, resolved) != NULL) cwd_real = strdup(resolved);
    int v = entry_is_caller_influenced(c, cwd, cwd_real);
    free(cwd); free(cwd_real);
    return v;
}

/* Enforce the path policy: no caller-influenced entry on sys.path.
 *
 * 3.10  MUTATES, because PyConfig.safe_path does not exist there and
 *       nothing else keeps the launch directory off sys.path.
 * 3.11+ READ-ONLY. safe_path is the native control there; a second
 *       mutating implementation would only be able to MASK a
 *       configuration regression -- if safe_path stopped working, a
 *       scrub would hide it. So the invariant is CHECKED and init fails
 *       if it does not hold.
 *
 * Every uncertainty fails closed. Conversion failure, an unreadable
 * cwd, an undecidable entry, a failed deletion: all return -1, and
 * fr_udf_init refuses to initialise. The alternative -- skip and carry
 * on -- is how a suspect path survives into an interpreter that reports
 * a clean initialisation. */
static int enforce_path_policy(void)
{
    PyObject *path = PySys_GetObject("path");   /* borrowed */
    if (!path || !PyList_Check(path)) {
        set_error("sys.path is not a list; cannot enforce the path policy");
        return -1;
    }

    char *cwd = NULL, *cwd_real = NULL;
    if (resolve_cwd(&cwd) != 0) {
        set_error("cannot resolve the current directory; refusing to "
                  "initialise rather than assume sys.path is clean");
        return -1;
    }
    char resolved[PATH_MAX];
    if (realpath(cwd, resolved) != NULL)
        cwd_real = strdup(resolved);

#if PY_VERSION_HEX >= 0x030B0000
    /* Read-only verification of the native control. */
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(path); i++) {
        PyObject *e = PyList_GET_ITEM(path, i);   /* borrowed */
        if (!PyUnicode_Check(e)) {
            set_error("sys.path[%zd] is not a str; cannot verify the path "
                      "policy", (Py_ssize_t)i);
            goto fail;
        }
        PyObject *b = PyUnicode_AsUTF8String(e);
        if (!b) {
            set_error("sys.path[%zd] is not encodable as UTF-8; refusing "
                      "to initialise", (Py_ssize_t)i);
            PyErr_Clear();
            goto fail;
        }
        int verdict = entry_is_caller_influenced(PyBytes_AS_STRING(b),
                                                 cwd, cwd_real);
        const char *shown = PyBytes_AS_STRING(b);
        char copy[512];
        snprintf(copy, sizeof copy, "%s", shown ? shown : "(null)");
        Py_DECREF(b);
        if (verdict != 0) {
            set_error("sys.path[%zd] is a caller-influenced location "
                      "(\"%s\") despite PyConfig.safe_path; refusing to "
                      "initialise", (Py_ssize_t)i, copy);
            goto fail;
        }
    }
    free(cwd); free(cwd_real);
    return 0;
#else
    /* Downward iteration, so a deletion at index i does not disturb the
     * indices still to be visited (i-1 and below). An upward loop with
     * an unconditional i++ is the classic way to delete every OTHER
     * adjacent entry, so the direction is load-bearing and commented. */
    for (Py_ssize_t i = PyList_GET_SIZE(path) - 1; i >= 0; i--) {
        PyObject *e = PyList_GET_ITEM(path, i);   /* borrowed */
        if (!PyUnicode_Check(e)) {
            set_error("sys.path[%zd] is not a str; cannot verify the path "
                      "policy", (Py_ssize_t)i);
            goto fail;
        }
        /* UTF-8 is assumed here AND for cwd (both produced as UTF-8 by
         * getcwd/AsUTF8String), so the comparison is consistent. A
         * filesystem path with non-UTF-8 bytes would fail here, and
         * that must fail closed rather than skip the entry. */
        PyObject *b = PyUnicode_AsUTF8String(e);
        if (!b) {
            set_error("sys.path[%zd] is not encodable as UTF-8; refusing "
                      "to initialise", (Py_ssize_t)i);
            PyErr_Clear();
            goto fail;
        }
        int verdict = entry_is_caller_influenced(PyBytes_AS_STRING(b),
                                                 cwd, cwd_real);
        Py_DECREF(b);
        if (verdict < 0) {
            set_error("sys.path[%zd] cannot be classified; refusing to "
                      "initialise", (Py_ssize_t)i);
            goto fail;
        }
        if (verdict == 1) {
            /* PyList_SetSlice(.., NULL) deletes the slice.
             * PyList_DelSlice does not exist on 3.10. */
            if (PyList_SetSlice(path, i, i + 1, NULL) != 0) {
                set_error("failed to remove a caller-influenced sys.path "
                          "entry; refusing to initialise");
                goto fail;
            }
        }
    }
    free(cwd); free(cwd_real);
    return 0;
#endif

fail:
    free(cwd); free(cwd_real);
    return -1;
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
        if (!w) {
            take_exception(last_error, sizeof last_error, "decode root: ");
            return -1;
        }
        if (PyList_Insert(path, 0, w) != 0) {
            Py_DECREF(w);
            take_exception(last_error, sizeof last_error, "sys.path insert: ");
            return -1;
        }
        Py_DECREF(w);
    }
    return 0;
}


/* ------------------------------------------------------------------------ */
/* Exception handling                                                        */
/* ------------------------------------------------------------------------ */

/* Fold the pending exception into a concise one-line diagnostic and CLEAR
 * it. Never prints. Never exits.
 *
 * Why this exists instead of PyErr_Print():
 *
 *  1. PyErr_Print() writes a full traceback to stderr for EVERY failing
 *     batch, interleaved across workers.
 *  2. Far worse: for SystemExit it EXITS THE PROCESS rather than
 *     returning. A UDF calling sys.exit(3) therefore killed the worker
 *     outright -- the batch was lost and escrow/retry/skip/fail-fast were
 *     all bypassed, because the process died before any of them could
 *     run. That is a worker death manufactured out of what should be an
 *     ordinary batch-level payload error.
 *
 * Everything must be cleared, never left pending: a lingering exception
 * contaminates the next fr_udf_call() in ways that look like unrelated
 * bugs.
 *
 * PyErr_Fetch() is deprecated since 3.12 in favour of
 * PyErr_GetRaisedException(); both are handled so the helper builds
 * across the 3.10-3.15 target.
 *
 * Full tracebacks are opt-in via FR_UDF_TRACEBACK=1 for debugging. */
static void take_exception(char *buf, size_t bufsz, const char *prefix)
{
#if PY_VERSION_HEX >= 0x030C0000
    /* Clears the error and returns a NEW reference (3.12+). */
    PyObject *exc = PyErr_GetRaisedException();
#else
    PyObject *type = NULL, *val = NULL, *tb = NULL;
    PyErr_Fetch(&type, &val, &tb);            /* also clears */
    PyObject *exc = val ? val : type;
    Py_XINCREF(exc);
    Py_XDECREF(type);
#endif
    if (exc == NULL) {
        snprintf(buf, bufsz, "%s (no exception set)", prefix);
        return;
    }
    if (PyObject_IsTrue(PyObject_GetAttrString(exc, "__suppress_context__")) < 0)
        PyErr_Clear();

    PyObject *s = PyObject_Str(exc);
    const char *msg = "";
    if (s != NULL && PyUnicode_Check(s)) {
        const char *u = PyUnicode_AsUTF8(s);
        if (u != NULL) msg = u;
    }
    Py_XDECREF(s);

    /* Include the exception TYPE. str(SystemExit(3)) is just "3", so
     * without this a UDF calling sys.exit() reported "udf raised: 3" --
     * which says nothing about what went wrong. The type is the part
     * that tells an operator whether this is a bug in the UDF or a
     * deliberate early return. */
    const char *tn = Py_TYPE(exc)->tp_name;

    /* One line: a multi-line exception message would break the "concise
     * diagnostic" contract and, in a worker, interleave with other
     * workers' output. */
    char *tmp = (char *)malloc(bufsz);
    if (tmp) {
        size_t j = 0;
        for (size_t i = 0; prefix[i] && j + 1 < bufsz; i++)
            tmp[j++] = prefix[i];
        for (size_t i = 0; tn[i] && j + 2 < bufsz; i++)
            tmp[j++] = tn[i];
        if (j + 2 < bufsz) { tmp[j++] = ':'; tmp[j++] = ' '; }
        for (size_t i = 0; msg[i] && j + 1 < bufsz; i++)
            tmp[j++] = (msg[i] == '\n' || msg[i] == '\r') ? ' ' : msg[i];
        tmp[j] = '\0';
        snprintf(buf, bufsz, "%s", tmp);
        free(tmp);
    } else {
        snprintf(buf, bufsz, "%s%s: %s", prefix, tn, msg);
    }
    Py_XDECREF(exc);
    PyErr_Clear();   /* belt and braces: nothing pending on any path */
}

static int tracebacks_requested(void)
{
    const char *v = getenv("FR_UDF_TRACEBACK");
    return v && *v && strcmp(v, "0") != 0;
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
        if (PyErr_Occurred())
            take_exception(last_error, sizeof last_error, "init: ");
        return FR_UDF_ERR;
    }
    /* BEFORE install_roots: on 3.10 this is what stands in for
     * cfg->safe_path, and it has to happen while no caller-supplied root
     * is on the path yet. On 3.11+ it verifies rather than mutates, so
     * that a safe_path regression cannot be masked. */
    if (enforce_path_policy() != 0) {
        Py_FinalizeEx();
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
            take_exception(last_error, sizeof last_error,
                           "import failed: ");
            return FR_UDF_ERR;
        }
        PyObject *fn = PyObject_GetAttrString(m, attr);
        if (!fn) {
            take_exception(last_error, sizeof last_error,
                           "attribute lookup failed: ");
            Py_DECREF(m);
            return FR_UDF_ERR;
        }
        /* Non-callable is its own defined failure, not a call error.
         * Without this check the failure surfaces later, inside
         * PyObject_CallFunctionObjArgs, as a bare
         * "TypeError: 'int' object is not callable" traceback -- which
         * names neither the module nor the attribute, so a UDF wired up
         * as `mod:CONSTANT` instead of `mod:fn` reported as though the
         * call itself had gone wrong. */
        if (!PyCallable_Check(fn)) {
            set_error("%s.%s is not callable (%s)", module, attr,
                      Py_TYPE(fn)->tp_name);
            Py_DECREF(fn);
            Py_DECREF(m);
            return FR_UDF_ERR;
        }
        clear_cache();
        cached_module = m;      /* strong: keeps the module alive */
        cached_fn = fn;
        snprintf(cached_spec, sizeof cached_spec, "%s", spec);
    }

    PyObject *arg = PyBytes_FromStringAndSize(input ? input : "", (Py_ssize_t)len);
    if (!arg) { take_exception(last_error, sizeof last_error, "arg failed: "); return FR_UDF_ERR; }
    PyObject *res = PyObject_CallFunctionObjArgs(cached_fn, arg, NULL);
    Py_DECREF(arg);
    if (!res) {
        /* The important one. A SystemExit here used to END THE PROCESS
         * (PyErr_Print exits for SystemExit), turning an ordinary batch
         * error into a worker death that bypassed on_error entirely. */
        take_exception(last_error, sizeof last_error, "udf raised: ");
        if (tracebacks_requested() && PyErr_Occurred())
            PyErr_Print();       /* opt-in debugging only */
        return FR_UDF_ERR;
    }

    if (res == Py_None) {
        /* None: the UDF produced no result. Distinct from b"", and the
         * caller must be able to tell them apart -- see fr_udf.h. */
        Py_DECREF(res);
        return FR_UDF_NO_RESULT;
    }

    if (!PyBytes_Check(res)) {
        /* Clear first: the type probe below can itself set an error. */
        PyErr_Clear();
        set_error("%s returned %s, not bytes", spec, Py_TYPE(res)->tp_name);
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
        take_exception(last_error, sizeof last_error, "import probe: ");
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
