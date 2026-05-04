remove_frun_base64() {

if [[ "$1" ]] && [[ -f "$1" ]]; then
    frun_path="$1"
else
    frun_path="./frun.bash"
fi

[[ -f "$frun_path" ]] || return 1

if [[ "$2" ]]; then
    sed -E 's/^(declare -A b64=\().*$/\1)   # removed base64/' "${frun_path}" >"${2}"
else
    sed -i -E 's/^(declare -A b64=\().*$/\1)   # removed base64/' "${frun_path}"
fi

}

remove_frun_base64 "$@"
