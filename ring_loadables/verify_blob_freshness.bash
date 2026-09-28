#!/usr/bin/env bash
# verify_blob_freshness.bash — decode-and-cmp embed gate (W-REL5-F F4).
#
# Usage: verify_blob_freshness.bash <built.so> <frun.bash> <key>
#   <built.so>  freshly built loadable artifact for one arch
#   <frun.bash> script carrying the embedded base64 map
#   <key>       map key, e.g. x86_64_v4 (dashes become underscores)
#
# Proves the payload embedded in frun.bash decodes (via the repo's own
# decoder, checksums enforced) to bytes identical to the artifact.
# Mismatch ALWAYS fails (stale-blob shipping is structurally fatal —
# the F31 class: a silently failed update step once shipped stale
# blobs while verification passed). This is the R5 freshness logic
# extracted for reuse (release workflow + sanitizer legs); the BUILD
# half stays with the caller (flags differ per leg).
#
# NOTE on regen-and-compare: the encoder gzip-compresses with an
# embedded mtime, so two encodings of the SAME .so never compare
# equal. Decode-and-cmp proves embedded == artifact deterministically.
set -euo pipefail

if [[ $# -ne 3 ]]; then
    echo "usage: $0 <built.so> <frun.bash> <key>" >&2
    exit 2
fi
artifact="$1"
frun="$2"
key="$3"
[[ -f "$artifact" ]] || { echo "VERIFY-FAIL: missing artifact $artifact" >&2; exit 1; }
[[ -f "$frun" ]] || { echo "VERIFY-FAIL: missing frun.bash $frun" >&2; exit 1; }

# Repo machinery, sourced from frun.bash (function defs only — never
# source the whole file here). Extraction runs to the first column-0
# `}` after each opener (both functions end there).
# shellcheck disable=SC1090
. <( { capture=false; while IFS= read -r line; do
  case "$line" in
    *'_forkrun_file_to_base64() {'*|*'_forkrun_base64_to_file() {'*) capture=true;;
  esac
  $capture && printf '%s\n' "$line"
  $capture && [[ "$line" == '}' ]] && capture=false
done; } <"$frun" )
# Embedded map: eval ONLY the declare region between the
# _BASE64_START_ marker and the bootstrap line.
unset b64; declare -A b64=()
eval "$(awk '/_BASE64_START_/{f=1;next} /_forkrun_bootstrap_setup/{f=0} f' "$frun")"
# NOTE: the codec functions are foreign code that is not
# nounset-clean, so the call runs with its native options
# (subshell-scoped); the comparison below remains the hard gate.
tmpd="$(mktemp -d)"
trap 'rm -rf "$tmpd"' EXIT
if [[ -z "${b64[$key]:-}" ]]; then
    echo "VERIFY-FAIL: frun.bash carries no embedded b64[$key]" >&2
    exit 1
fi
if (set +e +u; _forkrun_base64_to_file <<<"${b64[$key]}" "$tmpd/out.so" 2>/dev/null); then
    if cmp -s "$tmpd/out.so" "$artifact"; then
        echo "VERIFY-OK: b64[$key] decodes to $artifact" >&2
        exit 0
    else
        echo "VERIFY-FAIL: embedded b64[$key] decodes to bytes differing from $artifact (stale blob)" >&2
        exit 1
    fi
else
    echo "VERIFY-FAIL: embedded b64[$key] failed to decode/verify" >&2
    exit 1
fi
