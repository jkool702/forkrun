# W-BASHCOMPAT Phase 0 — Diagnosis (READ-ONLY, no fix)

Branch `wrel5-beta` @ a435d97. Product files untouched; twins untouched.
All scratch (debs, tarballs, builds, logs) lives in /tmp/bashcompat — NOT in tree.

## Verdict

Failure mode is **none of (a)/(b)/(c)**. Modes (a–c) are REFUTED with hard
evidence below. Observed mode **(d): silent death while evaluating the single
901,574-byte line `declare -A b64=...` (frun.bash:2992)** — before ANY
`enable -f` ever executes. Plus one latent `-e` landmine (§0.1b) the fix phase
will hit immediately after.

## 0.1 Exact failure (verbatim CI stderr)

Runs 36372510312 (09-28, NEW/REFACTOR2.9) and 36337540403 (09-27,
NEW/REFACTOR2.7) — step "Bash smoke tests…", shell
`bash --noprofile --norc -e -o pipefail`, runner bash **5.2.21**, last output:

```
+ source ./frun.bash
++ shopt -q extglob
++ shopt -s extglob
++ complete -F _frun_complete frun
++ unset b64
++ b64=(['aarch64']='0 203464
md5sum:995b9ae589fdb8c836ffb79355649b2e
```

…then silence; step fails in ~1s (no hang, no error text). Death is ~50ms
into the 901,574-byte `declare -A b64=` line (:2992 here, :2861 on runner
branch — **byte-identical line, md5 67ccd5e6…**). Consistent across both days
(Sep-27 blob md5 `1bdf78…`, Sep-28 `995b9a…`). Bootstrap/`enable` never run.

Functional matrix on host (extracted Ubuntu binaries 4.4.20/5.0.17/5.1.16/
5.2.21/5.3.9, libc held at host 2.43 — see Blocked): `enable -f` + builtin
calls + FULL `source ./frun.bash` + `ring_version -a` + `frun -k` workload all
GREEN on **4.4, 5.0, 5.1, 5.2, 5.3** × blobs **v2/v3/v4**. So the loadable is
not version-locked; the (a)-hypothesis's proximate claim ("`enable -f` fails
on ≤5.2") does not reproduce — CI dies earlier, in pure-shell `declare`.

Repro gap: same bash build (5.2.21-2ubuntu4) + byte-identical line succeed here
in every mode tried (plain, `-e`, `-x`, step-file, 8MB stack, ASan build,
internal-malloc build; declare RSS ≈13MB both versions). Manifestation needs
the runner env (glibc 2.39 / kernel 6.8 / Azure CPU) — root-cause site inside
bash 5.2's giant-line handling is UNPROVEN; no upstream 5.3 CHANGES entry names
it (checked 5.3-alpha section top to bottom).

### 0.1b Latent `-e` landmine (proven by strace, version-INDEPENDENT)

`_forkrun_base64_to_file` (frun.bash:2488): `[[ -f "$1" ]] && \rm -f "$1"`.
On the final-memfd write (:2802–2803) `$1`=/proc/self/fd/N (live memfd) exists,
`rm` → EPERM rc=1, and `rm` follows the FINAL `&&` → **non-exempt → `-e`
kills the shell** (strace: `rm` exit(1) → parent `exit_group(1)`; reproduced on
5.2 AND 5.3 here). `&>/dev/null` hides rm's diagnostic (absent from all logs).
Without `-e` the failure is benign (`: >fd` truncates via open handle — why
local runs pass). CI's step shell IS `-e`: after any declare fix, bootstrap
dies HERE next. Flagging for fix phase; NOT the current CI killer (CI dies
earlier, with no `rm:` text).

## 0.2 Symbol-set diff — mode (a) REFUTED

`nm -D -u` shipped x86-64 .so → 12 bash symbols. Presence per version
(Y = exported; Ubuntu binaries + local 5.3.9):

| symbol | 4.4 | 5.0 | 5.1 | 5.2 | 5.3 | local 5.3.9 |
|---|---|---|---|---|---|---|
| bind/find/unbind_variable, bind_array_{element,variable}, bind_assoc_variable, make_new_array_variable, make_builtin_argv, get_string_value, builtin_error, xfree (11) | Y | Y | Y | Y | Y | Y |
| add_builtin | – | – | – | – | – | – |

`add_builtin` is absent EVERYWHERE incl. working 5.3 — and harmless:
bash `enable` dlopens RTLD_LAZY; LD_DEBUG proves it never binds; sole caller is
`setup_builtin_forkrun_ring` (forkrun_ring.c:10096), which nothing on the
enable path calls (bash core registers the exported `ring_*_struct` data
symbols itself — that is why `enable -f` succeeds on all versions).

## 0.3 Struct layout probe — mode (b) REFUTED (5.2↔5.3)

Upstream `builtins.h` **byte-identical 5.2↔5.3** (`diff` rc=0). Probe vs local
5.3 headers: `sizeof(struct builtin)=48`, offsets 0/8/16/24/32/40, flags
ENABLED=1…REQUIRES=256 — identical by construction for 5.2. `variables.h`
5.2→5.3 diff is PARAMS→prototype modernization + const-correctness only
(`bind_variable` const change is ABI-identical); no used-symbol ABI drift.
Mode (c) REFUTED for all 12 required symbols. (<5.2 headers unavailable
statically; layout compat proven functionally via enable+call on 4.4–5.1.)

## 0.4 Provenance — weak 5.3-headers hypothesis CONFIRMED, strong form REFUTED

Blobs built in CI `fedora:latest` containers (`dnf install bash-devel`;
Sep-2026 Fedora → 5.3 headers), GCC 16.2.1 Red Hat (matches .so `.comment`),
`-O3 -flto… -I/usr/include/bash… -DSHELL -DHAVE_CONFIG_H`, per-arch
BUILD_ARCH, `strip`, sanity `enable -f` + freshness byte-compare gate
(forkrun_release.yml:63–148). Embedded via base64 (`-`→`_` keys) into
frun.bash; latest refresh 857f49e (only riscv64 bytes changed). So: built
against 5.3 headers = TRUE; "references ≥1 symbol ≤5.2 lacks" = FALSE (§0.2).

## 0.5 Dependency-floor mapping (19 canary stubs × export sets)

Floor of the ACTUAL .so requirement set: **4.4** (all 11 real symbols exported
since 4.4). 14/19 stubs present 4.4→5.3; 5 stubs exported NOWHERE
(`bind_var_or_array`, `array_p`, `array_cell`, `add_builtin`, `xmalloc_dup`) =
canary-only boundary markers, never resolved at runtime (cross-checked vs .so
U-list). Canary's structural blind spot confirmed: it freezes the closure but
cannot see single-line-size/data-volume hazards like :2992.

## Blocked legs (explicit)

Per-version **Docker container** captures (bash 4.4/5.0/5.1/5.2/5.3 pinned
images, verbatim `enable -f` stderr): **BLOCKED** — `docker info` → permission
denied on /var/run/docker.sock (client 29.7.2, no daemon access; unchanged).
Substituted with extracted distro binaries + upstream tarballs; gap: libc held
at host 2.43, so the runner-specific declare crash is localized but its exact
trigger site is unproven. No fix, no canary/CI/blob changes per orders.

## Floor recommendation (for owner ratification)

**4.4** (mapfile `-d` needs 4.4 per E13; RHEL 8 audience) — evidence: §0.2/§0.5
tables (full requirement set exported since 4.4; functional green 4.4→5.3
here). The current CI failure is NOT a floor violation; fixing it is about the
0.9MB single-line `declare` (+ the §0.1b `rm`/memfd `-e` interaction), not
about symbols or layout. HALT after this commit — no fix phase attempted.
