#!/usr/bin/env bash

getdeps() (
## analyzes a shell script to determine its dependencies

    shopt -s extglob

    DEBUG_trap='type -p "${BASH_COMMAND%% *}" >>"'"${PWD}"'/deps"; 
echo "${FUNCNAME:-"${BASH_SOURCE:-"$0"}"}:${LINENO}" >>"'"${PWD}"'/coverage"; 
echo "${BASH_CMDS[@]}" >>"'"${PWD}"'/cmds"; 
[[ "${DEBUG_declaredFunctionNames[*]}" == *"${FUNCNAME}"* ]] || { declare -F "${FUNCNAME}" &>/dev/null && { declare -f "${FUNCNAME}" 2>/dev/null >>"'"${PWD}"'/funcs"; echo "${FUNCNAME}" >>"'"${PWD}"'/funcnames"; DEBUG_declaredFunctionNames+=("${FUNCNAME}"); }; }'

    if [[ "$1" == $'\034' ]]; then
        printAllDepsFlag=false
        shift 1
    else
        printAllDepsFlag=false
    fi
        

    scriptpath="$1"

    shift 1

            scriptname="${scriptpath##*\/}"
            scriptname="${scriptname//+([[:space:]])/_}"

            fname="fun_${RANDOM}${RANDOM}"

            for nn in deps deps.guess deps.all deps.guess.all coverage *.coverage.missed cmds funcs funcnames xtrace; do
                [[ -f "${PWD}/${nn}" ]] && \mv -f "${PWD}/${nn}" "${PWD}/${nn}.old"
                touch "${PWD}/${nn}"
            done

            type -p bash >>deps

            hash -r

            source /proc/self/fd/0 <<EOF
${fname}() (
hash -r
BASH_XTRACEFD=5
set -T
set -h
set -x
local -a DEBUG_declaredFunctionNames=("$fname")
trap '${DEBUG_trap}' DEBUG

$(cat "${scriptpath}")
) 5>${PWD}/xtrace
EOF

            ${fname} "$@"

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
                grep -F -q "${F[$kk]}" <deps || echo "${F[$kk]}"
            done >deps.guess

            echo "$(sort -u <deps.guess)" >deps.guess

            printf '\n\nDEPENDENCIES DETERMINED FOR: %s\n\nDEPENDENCIES FOUND FROM EXECUTED CODE:\n%s\n' "${scriptpath}" "$(<deps)"

            [[ $(<deps.guess) ]] && printf '\nGUESSED DEPENDENCIES FROM "MISSED" CODE:\n%s\n' "$(<deps.guess)"

            cat deps >>deps.all
            cat deps.guess >>deps.guess.all

            mapfile -t mdeps < <(file -f deps | grep ASCII | sed -E s/'\:[[:space:]]+.*$'// | while read -r; do grep -F "${REPLY}" <xtrace | grep -v 'type -p'; done)
            mapfile -t fdeps < <(file -f deps.guess | grep ASCII | sed -E s/'\:[[:space:]]+.*$'//)

        (( ${#mdeps[@]} > 0 )) && for kk in "${!mdeps[@]}"; do
            getdeps $'\034' ${mdeps[$kk]}
            ${printAllDepsFlag} && {
                printf '\n\nDEPENDENCIES DETERMINED FOR %s AND ALL DEPENDENT SCRIPTS CALLED BY IT\n\nDEPENDENCIES FOUND FROM EXECUTED CODE:\n%s\n' "${scriptpath}" "$(<deps.all)"

            [[ $(<deps.guess.all) ]] && printf '\nALL GUESSED DEPENDENCIES FROM "MISSED" CODE:\n%s\n' "$(<deps.guess.all)"

            }
        done

            (( ${#fdeps[@]} > 0 )) && printf '\nWARNING: THE FOLLOWING SHELL SCRIPTS ARE INCLUDED IN THE "GUESSED DEPENDENCIES" FROM ANALYSING CODE THAT WAS NOT EXECUTED:\N%s\n\nTHESE HAVE NOT BEEN RECURSVELY CHECKED FOR THEIR OWN DEPENDENCIES.\nAS SUCH, THE LIST OF DEPENDENCIES MAY BE INCOMPLETE.\nTO GET A MORE COMPLETE LIST, INCREASE CODE COVERAGE AND ENSURE THESE SHELL SCRIPTS ARE EXECUTED.' "${fdeps[*]}"

            for nn in deps deps.guess deps.all deps.guess.all coverage *.coverage.missed cmds funcs funcnames xtrace; do
                [[ "$nn" == "${scriptname}".* ]] && continue
                [[ -f "${scriptname}.${nn}" ]] && \mv "${scriptname}.${nn}" "${scriptname}.${nn}.old"
                \mv -f "${nn}" "${scriptname}.${nn}"
            done

            printf '\nINFORMATION related to dependencies and coverage \nhas been saved in various files located at: %s/%s.*\n\n' "${PWD}" "${scriptname}"

)
