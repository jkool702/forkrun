remove_frun_base64() {

if [[ "$1" ]] && [[ -f "$1" ]]; then
    frun_path="$1"
else
    frun_path="./frun.bash"
fi

[[ -f "$frun_path" ]] || return 1

# W-BASHCOMPAT-BC1: chunked payloads span many lines — delete the
# whole START..END region (the old single-line sed left every
# b64[k]+= chunk behind, producing a "payload-less" twin that
# still carried the full payload). Files predating END markers
# keep the legacy single-line behavior.
_strip_to() {
    if grep -q '# <@@@@@< _BASE64_END_ >@@@@@> #' "$1"; then
        awk '
            /# <@@@@@< _BASE64_START_ >@@@@@> #/ {
                print
                print ""
                print "declare -A b64=()   # removed base64"
                print "# <@@@@@< _BASE64_END_ >@@@@@> #"
                skip = 1
                next
            }
            skip && /# <@@@@@< _BASE64_END_ >@@@@@> #/ { skip = 0; next }
            !skip { print }
        ' "$1" >"$2"
    else
        sed -E 's/^(declare -A b64=\().*$/\1)   # removed base64/' "$1" >"$2"
    fi
}

if [[ "$2" ]]; then
    _strip_to "${frun_path}" "${2}"
else
    _tmp_out="$(mktemp)" || return 1
    _strip_to "${frun_path}" "${_tmp_out}" && command mv -f "${_tmp_out}" "${frun_path}"
fi

}

# W-BASHCOMPAT-BC1: only run on EXECUTION, never on source. Sourcing
# this file (e.g. to reuse the function) with empty "$@" used to
# fall into the in-place branch and rewrite ./frun.bash of the
# caller's cwd as a side effect — that destroyed a tree copy during
# this wave's own verification. Explicit paths are still honored.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    remove_frun_base64 "$@"
fi
