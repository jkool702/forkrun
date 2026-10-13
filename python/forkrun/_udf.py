"""UDF (Python callable) support for the cleanroom launcher -- P1-3.

A UDF is named as ``"module:attribute"`` and executed inside a worker by
the embedded interpreter in ``_fr_udf*.so``, not by this process. That
distinction drives almost everything here:

* The helper is **per-minor** (it links libpython and uses the full
  configuration API, which is not in the Stable ABI -- DECISION-01
  sections 2.1/7), so it is discovered by ``EXT_SUFFIX``.
* The helper **cannot be loaded into a process that already runs Python**
  (it calls ``Py_InitializeFromConfig``). This module therefore never
  imports the user's UDF and never touches the helper; it only locates
  the file and derives roots. Execution happens in the launcher, which
  is ``exec``'d and has no interpreter of its own.
* Roots are derived from **this** interpreter's site configuration, never
  hardcoded. With ``site_import = 0`` -- required for isolation -- *no*
  site root is added automatically, not even the system one, so a UDF's
  transitive dependencies routinely span roots (DECISION-01 section 8,
  finding 1).

The one deliberate asymmetry with ``mode="plugin"``: this module does
NOT resolve the spec in the parent. ``mode="plugin"`` parses
``path:function`` here; a UDF spec is resolved *inside* the launcher, so
that user-module import and module globals stay worker-local. Importing
a user's module in the parent would put their state into the process that
later forks every worker -- exactly the inheritance the cleanroom
exists to prevent (external review, confirmation pass, requirement 3).
"""

import os
import sys
import sysconfig

__all__ = ["UDFError", "helper_path", "candidate_helper_path",
           "roots_spec", "parse_spec",
           "udf_payload", "caller_version_arg", "helper_fingerprint",
           "known_incompatible", "record_incompatible", "clear_incompatibles"]


# --- compatibility state -------------------------------------------------
#
# A confirmed mismatch is remembered so the same unusable artifact is not
# re-probed (re-exec + dlopen) on every call. Three rules, each from
# review:
#
#   1. This cache may only ever DISABLE the accelerator. It must never
#      authorise running an unverified helper.
#   2. The key is a METADATA FINGERPRINT, not a cryptographic identity.
#      A collision can unnecessarily disable cleanroom execution; it can
#      never enable an unverified one.
#   3. A PROBE TIMEOUT is inconclusive and is therefore NOT cached. Only a
#      conclusive mismatch or a missing-version-symbol result is.
_UDF_VERSION = sys.version_info[:2]
_INCOMPATIBLE = {}          # fingerprint -> human-readable reason


def caller_version_arg():
    """``--caller-version=MAJOR.MINOR`` from THIS interpreter.

    A declaration, not an authenticated identity: after exec the launcher
    cannot know which interpreter started it. It comes from
    sys.version_info and nothing else -- not an environment variable, not
    a separate probe -- so the declaration is not forgeable by a stray
    FORKRUN_* in the environment.
    """
    return "--caller-version=%d.%d" % _UDF_VERSION


def helper_fingerprint(path):
    """Metadata fingerprint of a helper artifact, or None if unavailable.

    ``st_ctime_ns`` is included alongside mtime so an in-place rewrite that
    restores the modification time still changes the key.

    Returns None when the identity cannot be obtained -- in which case
    NOTHING is cached, because a missing fingerprint cannot safely stand
    in for "same artifact".
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def known_incompatible(path):
    """Reason this exact artifact was refused, or None."""
    if not path:
        return None
    fp = helper_fingerprint(path)
    if fp is None:
        return None
    return _INCOMPATIBLE.get(fp)


def record_incompatible(path, reason):
    """Remember a CONCLUSIVE refusal so it is not re-probed.

    ``reason`` is the launcher diagnostic. Only conclusive outcomes are
    recorded; a probe timeout must not be passed here.
    """
    fp = helper_fingerprint(path) if path else None
    if fp is not None:
        _INCOMPATIBLE[fp] = reason


def clear_incompatibles():
    """Test/operator hook: forget every recorded incompatibility."""
    _INCOMPATIBLE.clear()


class UDFError(Exception):
    """UDF mode is unavailable or misconfigured."""


def candidate_helper_path():
    """The helper that WOULD be used, ignoring the incompatibility cache.

    Needed because helper_path() returns None once an artifact is known
    bad -- so asking it "which artifact did we reject?" always answers
    "none" and the per-invocation warning goes silent after the first
    call. The cache must not be able to hide the reason it exists.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    cand = os.path.join(here, "_fr_udf" + suffix)
    if os.path.exists(cand):
        return cand
    plain = os.path.join(here, "_fr_udf.so")
    return plain if os.path.exists(plain) else None


def helper_path():
    """Absolute path to the per-minor helper, or None if not built.

    Built by ``make -f Makefile.substrate udf-lib``. Absence is a
    *reported* condition, not an exception: the caller treats a missing
    helper as "cleanroom unavailable for this call" and falls back to
    the in-process path, which is slower and correct.
    """
    # KILL SWITCH (W-EXP-1 5.5 / roadmap 5.3): FORKRUN_NO_UDF masks ONLY
    # this capability, and deliberately is NOT a mirror of
    # FORKRUN_NO_V1 -- that one forces every v1 fast path off, because
    # they are all substrate symbols read from one place. The UDF helper
    # is a separate per-minor file whose existence is consulted from
    # several routes, so masking it at the lookup keeps every caller in
    # agreement instead of relying on each one to remember.
    #
    # Returning None (rather than raising) is what "forces in-process"
    # means here: absence is already a reported, handled condition that
    # falls back to the in-process path.
    if os.environ.get("FORKRUN_NO_UDF"):
        return None

    here = os.path.dirname(os.path.abspath(__file__))
    suffix = sysconfig.get_config_var("EXT_SUFFIX") or ".so"
    cand = os.path.join(here, "_fr_udf" + suffix)
    if os.path.exists(cand):
        # A helper this launcher has conclusively REFUSED is not a
        # candidate. Reporting it as present would be a capability lie
        # about an artifact we already know cannot serve this caller --
        # and the boolean's contract is "a candidate helper exists", not
        # "a usable one does".
        #
        # This may only ever DISABLE the accelerator. It is consulted on
        # the way to a refusal, never on the way to authorising a load.
        if known_incompatible(cand):
            return None
        return cand
    # Fall back to a plain .so so a build that used a different suffix
    # still works, rather than silently disabling the feature.
    #
    # NOTE this fallback also defeats suffix-based IDENTIFICATION, which
    # is why a filename match is not treated as a version check anywhere.
    plain = os.path.join(here, "_fr_udf.so")
    return plain if os.path.exists(plain) else None


def _udf_dir(module):
    """Directory containing ``module``, found WITHOUT importing it.

    Isolation means the worker's interpreter starts with no inherited
    search path, so a UDF placed anywhere other than a site-packages
    root would be unimportable -- every batch would fail, retry, and
    eventually poison. That is a real trap, not a hypothetical: it is
    exactly what happened on the first end-to-end run.

    So the module's location is resolved HERE, explicitly, by scanning
    sys.path for a matching file. Scanning for a filename executes no
    user code -- unlike resolving the spec, which would import it. The
    result is still an explicit allowlist handed to the worker, never an
    inherited search path.

    Returns None for a dotted spec (``pkg.mod``), where the top-level
    package directory is what matters and guessing would be worse than
    letting the caller add a root.
    """
    if "." in module:
        return None
    base = os.path.basename(module)
    for entry in sys.path:
        if not entry:
            entry = os.getcwd()
        try:
            cand = os.path.join(entry, base + ".py")
            if os.path.isfile(cand):
                return entry
            pkg = os.path.join(entry, base, "__init__.py")
            if os.path.isfile(pkg):
                return entry
        except OSError:
            continue
    return None


def roots_spec(module=None):
    """Space-separated validated import roots for the embedded interpreter.

    Derived from this interpreter's own ``site`` configuration, in the
    documented order: system site roots first, then the user root. The
    launcher validates each for readability before the interpreter sees
    it, and the helper installs them in this order, so the first root
    wins any shadowing contest.

    Never cached: ``pip install --user`` during a long-lived process
    would otherwise be invisible to later calls.
    """
    import site

    roots = []
    try:
        system = site.getsitepackages()
    except Exception:
        system = []
    if isinstance(system, str):
        system = [system]
    for p in system:
        if p and p not in roots and os.path.isdir(p):
            roots.append(p)
    try:
        user = site.getusersitepackages()
    except Exception:
        user = None
    if isinstance(user, str) and user not in roots and os.path.isdir(user):
        roots.append(user)
    # The UDF's own directory goes FIRST so it wins any shadowing
    # contest against a same-named installed package -- the user's own
    # file is the one they meant.
    if module:
        d = _udf_dir(module)
        if d and d not in roots:
            roots.insert(0, d)
    # User root only exists after creation; pip creates it lazily, so a
    # missing one is normal and must not be invented or warned about.
    return " ".join(roots)


def parse_spec(payload):
    """``"module:attribute"`` -> ``(module, attribute)``.

    rpartition on the last colon, exactly as ``_coerce_payload`` does for
    ``mode="plugin"``, so ``pkg.mod:Class.method`` splits the same way.
    """
    if not isinstance(payload, str) or ":" not in payload:
        raise UDFError(
            "mode='udf' payload must be 'module:attribute' format, got %r"
            % (payload,))
    module, _, attr = payload.rpartition(":")
    if not module or not attr:
        raise UDFError(
            "mode='udf' payload must be 'module:attribute' format, got %r"
            % (payload,))
    return module, attr


class _UDFPayload(object):
    """Carries the spec to the launcher without importing anything here.

    Deliberately NOT a callable. ``mode="plugin"`` builds a ctypes
    payload resolved in the parent; a UDF must not be. This object is
    only ever read by the launcher-argv builder, so nothing can call it
    by accident.
    """

    __slots__ = ("module", "attr")

    def __init__(self, module, attr):
        self.module = module
        self.attr = attr

    def __repr__(self):
        return "<udf %s:%s>" % (self.module, self.attr)


def udf_payload(payload):
    """Validate and wrap a UDF spec. Does not import the module."""
    module, attr = parse_spec(payload)
    return _UDFPayload(module, attr)