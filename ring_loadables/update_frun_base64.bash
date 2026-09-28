
update_frun_base64() (

if [[ "$1" ]] && [[ -f "$1" ]]; then
    frun_path="$1"
else
    frun_path="./frun.bash"
fi

[[ -f "$frun_path" ]] || return 1

. <( { echoFlag=false; while true; do IFS= read -r line; [[ "$line" == *'_forkrun_file_to_base64() {'* ]] && echoFlag=true; $echoFlag && echo "$line"; $echoFlag && [[ "$line" == '}'* ]] && break; done; } <"${frun_path}" )

( 
unset b64
declare -A b64
shopt -s globstar
for nn in ./*.so; do
mm="${nn#*forkrun_ring.}"
mm="${mm%.so}"
mm="${mm//-/_}"
b64[$mm]="$(_forkrun_file_to_base64 "$nn")"
done
{          
while IFS= read -r line; do
echo "$line"
[[ "$line" == *'# <@@@@@< _BASE64_START_ >@@@@@> #'* ]] && break
done
echo
# W-BASHCOMPAT-BC1: chunked emission (mirror of
# _forkrun_b64_emit_chunked in frun.bash — keep in sync). A single
# `declare -p` line is the 0.9MB death on older bash.
echo '# W-BASHCOMPAT-BC1: chunked b64 payload, 32KiB %q appends (see _forkrun_b64_emit_chunked; regenerated region, do not hand-edit).'
echo 'declare -A b64=()'
while IFS= read -r _bck; do
    [[ -n ${_bck} ]] || continue
    _bcv=${b64[${_bck}]}
    if [[ -z ${_bcv} ]]; then
        printf 'b64[%q]+=%q\n' "${_bck}" ""
        continue
    fi
    while [[ -n ${_bcv} ]]; do
        printf 'b64[%q]+=%q\n' "${_bck}" "${_bcv:0:32768}"
        _bcv=${_bcv:32768}
    done
done < <(printf '%s\n' "${!b64[@]}" | LC_ALL=C sort)
# Preserve the file tail verbatim (post-A5 the payload is followed by
# the nounset save/restore + bootstrap invocation — the old shape
# dropped everything after the payload and re-appended --force,
# which would truncate that tail).
_past_payload=false
while IFS= read -r line || [[ -n $line ]]; do
    if ! $_past_payload; then
        # Skip the old payload region: blanks, the single declare,
        # chunked appends, and this block's own comment lines.
        [[ -z ${line} ]] && continue
        [[ "${line}" == 'declare -A b64='* ]] && continue
        [[ "${line}" == 'b64['*']+='* ]] && continue
        [[ "${line}" == '# W-BASHCOMPAT-BC1'* ]] && continue
        _past_payload=true
        # Re-add the single blank separator the skip consumed.
        echo
    fi
    echo "$line"
done
} <"${frun_path}" >"${frun_path%.bash}.new.bash"

[[ -s "${frun_path%.bash}.new.bash" ]] && command mv -f "${frun_path%.bash}.new.bash" "${frun_path}"

)

)
