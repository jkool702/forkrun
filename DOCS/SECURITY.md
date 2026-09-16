# forkrun Security Model

## Threat Model

A resume file (`.forkrun_resume`) is a file that tells forkrun *what to execute*.
By design, it is written by forkrun itself — but files can be shared, spooled,
left in scratch directories, or tampered with between crash and resume. forkrun
treats the resume file as **untrusted input that must prove itself** before any
of its content executes parent-side.

forkrun is an engine for running arbitrary code by design; the consent gate —
truthful and non-bypassable — is the security model. What the v3.5.1 hardening
(F29) closed was code executing without ever appearing in a preview, and forged
data executing while the preview showed the file's benign text.

## The Three Layers

### Layer 1 — Filesystem ownership (primary trust boundary)

Only the file's owner may dictate what an auto-resume executes. Since v3.5.1
(F29-B) this gate runs AFTER the sandbox extraction, so every consent prompt
previews post-parse extracted values (what will RUN) instead of raw file text.
The sandbox therefore necessarily runs before the ownership prompt — containing
pre-consent execution is the sandbox's designed job — and TTY-less paths still
fail closed before any parent-side eval.

- Foreign-owned file → hard reject; interactive preview + confirmation if a TTY
  is available, fail closed otherwise.
- Own file with group/world-writable bits → soft reject: fix with `chmod go-w`,
  confirm interactively, or `FORKRUN_TRUST_RESUME=1`.
- Un-stat-able file (broken symlink, race) → fail closed.

### Layer 2 — The restricted sandbox (secondary boundary)

Full-auto resume (`frun --resume FILE` with no command re-supplied) reconstructs
the execution environment inside a `bash --restricted` sandbox with an
environment that is **constructed, not cleared** (`env -i PATH='' ...`):

- PATH is set-empty at execve time (note: an *unset* PATH would trigger bash's
  compiled-in default — this is why the environment is built explicitly).
- Output redirection is prohibited (restricted mode) — no file writes.
- `source`/`.` with path arguments is prohibited.
- All shell functions are **wiped** after the file's definitions have been
  captured (as verified text) and before any variable rendering or emission.
- Variable state is re-rendered via `declare -p` and **round-trip verified**:
  serialization that does not survive eval→re-render→compare is rejected rather
  than imported (this rejects e.g. setups embedding command substitution).
- Emission is bounded by per-run frame tokens; the parent rejects output not
  framed by both tokens. Positional delivery is closed by construction (tokens
  arrive positionally but are immediately bound to readonly names and shifted
  away; emission goes only through an EXIT trap installed after verification,
  so early-exit forgeries emit token-less output). The `/proc/self/cmdline`
  channel is closed the same way the positional one is: a token-bounded
  forgery still passes the shape filter but is neutralized by the re-render.
  **Token secrecy is therefore NOT a security property** — tokens are an
  integrity mechanism (framing), not a secret. Tests T1g/T1h/T1a-ext forge
  with full token knowledge and still execute nothing.
- CWD-planted binaries (F6 characterization, 2026-09-16, bash 5.3.9): an empty
  PATH resolves CWD (`command -v touch` → `./touch` when a wrapper is planted;
  `command not found` with no planted binary — there is no default-PATH
  fallback). So a same-UID attacker who can write the resume CWD can get a
  planted binary executed pre-consent, in-sandbox, as the victim. Contained by
  design: restricted mode, function wipe, value neutralization (T1b/T1h prove
  the VALUES still don't cross), TRUST non-rebinding (denylist), and no
  parent-side execution of extracted text. Characterize-only (probe F6); the
  residual below states the boundary.

### Layer 3 — Interactive authorization (decision point)

Variables cross immediately. **Function definitions and setup commands cross in
a separate frame and are eval'd only after this gate**: the user must confirm
(y) interactively, or the environment must carry `FORKRUN_TRUST_RESUME=1`.
Headless + untrusted content = fail closed. The gate's own preview commands run
before any resume-supplied function exists in scope. A preview helper renders
the extracted frames at all three consent sites, so the user always confirms
what will run.

## Documented residuals (accepted for v3.5.1)

1. **Pre-consent code execution is limited to same-UID file tampering.**
   Reaching the sandbox requires local write access to the victim's resume file
   or resume CWD (F6's planted binary included); cross-UID attack is stopped by
   the ownership gate. Mitigated by the permission gate + informed consent —
   the documented threat boundary.
2. **Same-UID hostile content can shadow the interactive `read` prompt** (the
   layer-3 prompt itself is a builtin that hostile functions could shadow, if the
   hostile file already passed the sandbox — which requires same-UID write access
   to a resume file you own). Boundary of the threat model.
3. **Capture-time `builtin` shadowing** could forge the verified function text;
   the forged text still lands behind the layer-3 gate, so no additional
   privilege is gained.
4. **"Fallow may precede checkpoint" is safe only while resume semantics remain
   regenerate-from-source.** The input memfd may have holes beyond the checkpoint
   horizon; resume re-ingests the original stream, so this is invisible. Any
   future feature that reuses a crashed run's memfd must re-derive this proof.
