#!/usr/bin/env bash

getdeps() (
## analyzes a shell script to determine its dependencies

    shopt -s extglob

    DEBUG_trap='type -p "${BASH_COMMAND%% *}" >>"'"${PWD}"'/deps"; 
echo "${FUNCNAME:-"${BASH_SOURCE:-"$0"}"}:${LINENO}" >>"'"${PWD}"'/coverage"; 
echo "${BASH_CMDS[@]}" >>"'"${PWD}"'/cmds"; 
[[ "${DEBUG_declaredFunctionNames[*]}" == *"${FUNCNAME}"* ]] || { declare -F "${FUNCNAME}" &>/dev/null && { declare -f "${FUNCNAME}" 2>/dev/null >>"'"${PWD}"'/funcs"; echo "${FUNCNAME}" >>"'"${PWD}"'/funcnames"; DEBUG_declaredFunctionNames+=("${FUNCNAME}"); }; }'

    for scriptpath in "$@"; do
        (

            scriptname="${scriptpath##*\/}"
            scriptname="${scriptname//+([[:space:]])/_}"

            fname="fun_${RANDOM}${RANDOM}"

            for nn in deps deps.guess coverage *.coverage.missed cmds funcs funcnames; do
                [[ -f "${PWD}/${nn}" ]] && \mv -f "${PWD}/${nn}" "${PWD}/${nn}.old"
            done

            hash -r

            source /proc/self/fd/0 <<EOF
${fname}() (
hash -r
set -T
set -h
local -a DEBUG_declaredFunctionNames=("$fname")
trap '${DEBUG_trap}' DEBUG

$(cat "${scriptpath}")
)
EOF

            ${fname}

            trap -- DEBUG

            source funcs
            fname_def="$(declare -f "$fname")"
            cat funcnames | while read -r; do
                declare -f "$REPLY" &>/dev/null && fname_def="${fname_def//"$(declare -f "$REPLY")"/}"
            done
            echo "${fname_def}" >>funcs

            {
                printf '\n'
                printf '%s\n' $(<cmds) | sort -u
            } >>deps
            echo "$(sort -u <deps)" >deps
            echo "$(sort -t':' -k1,2 -V <coverage | uniq)" >coverage

            source funcs

            cat funcnames | while read -r funcname; do
                mapfile -t F < <(declare -f "$funcname")
                while read -r funcline; do
                    F[$funcline]=''
                done < <(grep -F "${funcname}"':' <coverage | sed -E s/'^[^:]*\:'//)

                printf '%s\n' "${F[@]}" >"${scriptname}.${funcname}.coverage.missed"
                mapfile -t F < <(printf '%s\n' "${F[@]// +(['&|']) /$'\n'}")
                mapfile -t F < <(printf '%s\n' "${F[@]//['$<>']'('/$'\n'}")
                mapfile -t F < <(printf '%s\n' "${F[@]//@('eval'|'exec')' '/$'\n'}" | sed -E 's/[[:space:]]+/ /g;s/^[[:space:]\(\{]*//;s/(\/usr\/?)?(\/bin\/?)?bash -c ["'"'"']*/\n/g;s/ .*$//;s/\;$//' | grep -E '[^[:space:]]+' | sort -u)
                type -p "${F[@]}" 2>/dev/null >>deps.guess
            done

            mapfile -t F <deps.guess

            for kk in "${!F[@]}"; do
                grep -F -q "${F[$kk]}" <deps && F[$kk]=''
            done

            F=(${F[@]})

            printf '%s\n' "${F[@]}" >deps.guess

            printf '\n\nDEPENDENCIES DETERMINED FOR: %s\n\nDEPENDENCIES FOUND FROM EXECUTED CODE:\n%s\n' "${scriptpath}" "$(<deps)"

            [[ $(<deps.guess) ]] && printf '\nGUESSED DEPENDENCIES FROM "MISSED" CODE:\n%s\n' "$(<deps.guess)"

            for nn in deps deps.guess coverage *.coverage.missed cmds funcs funcnames; do
                [[ "$nn" == "${scriptname}".* ]] && continue
                [[ -f "${scriptname}.${nn}" ]] && \mv "${scriptname}.${nn}" "${scriptname}.${nn}.old"
                \mv -f "${nn}" "${scriptname}.${nn}"
            done

            printf '\nINFORMATION related to dependencies and coverage \nhas been saved in various files located at: %s/%s.*\n\n' "${PWD}" "${scriptname}"

        )
    done
)
