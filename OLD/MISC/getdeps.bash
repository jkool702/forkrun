#!/usr/bin/env bash

shopt -s extglob

getdeps() (
    ## analyzes a shell script / function to determine its dependencies using a hybrid dynamic + static analysis
    #
    # the dependency list generated by the dynamic analysis is accurate but only includes dependency from code branches that are actually executed
    # the dependency list generated by the static analysiis works on the part of the code not executed to provide a "best guess" of its dependencies 
    # to get a "perfect" dependency list, make a scippt to call your code as many times as needed to get 100% code coverage
    #
    # USAGE:    [ <stdin> | ] getdeps $codeToAnalyse [ ${args[@]} ]
    #     1st input is the script / shell function to analyse
    #     remaining inputs (if any) are passed to that script/function when getdeps calls it
    #     if data is passed on stdin it will be passed to that script/function's stdin when getdeps calls it
    #
    # LIMITATIONS:
    #     getdeps utalizes a DEBUG trap, and will not work on script/functions that themselves use the DEBUG trap
    #     any nested calls to shell scripts will end up being run twice - once to get the actual invocation[s], then again running those invocation[s] through getdeps

    shopt -s extglob
    shopt -s extdebug

    local DEBUG_trap cfun printAllDepsFlag scriptpath scriptname fname fname_def funcsrc funcname kk shellFuncFlag stdinFlag
    local -a F mdeps fdeps

    # determine if getdeps has called itself. 
    # if so dont print filal dep list and dont make new tmpdir.
    cfun="$(caller 0)"
    cfun="${cfun#* }"
    cfun="${cfun% *}"

    if [[ "$cfun" == 'getdeps' ]]; then
                printAllDepsFlag=false
    else
                printAllDepsFlag=true
                local tmpdir="$(mktemp -d -t getdeps.XXXXXX)"
    fi

    # determine if we need to pass stdin to the script we will be running
    [ -t 0 ] && stdinFlag=false || stdinFlag=true
    
    # get scrupt path/name/type
    scriptpath="$1"

    scriptname="${scriptpath##*\/}"
    scriptname="${scriptname//+([[:space:]])/_}"
    scriptname="${scriptname//+([^[:print:]])/}"

    shift 1

    if [[ -f "${scriptpath}" ]]; then
        # $1 was standard shell script
        type -p realpath &>/dev/null && scriptpath="$(realpath "${scriptpath}")"
        shellFuncFlag=false

    elif declare -F "${scriptname}" &>/dev/null; then
        # $1 was a shell function. Generate a script to run it that ill work with getdeps.
        declare -f "${scriptname}" >"${tmpdir}"/"${scriptname}".script.src
        cat<<EOF >"${tmpdir}"/"${scriptname}".script
$(${stdinFlag} && printf 'cat |') ${scriptname} "\${@}" $(${stdinFlag})
EOF
        scriptpath="${tmpdir}"/"${scriptname}".script
        chmod +x "${scriptpath}"
        shellFuncFlag=true

    elif type -p "${scriptname}" &>/dev/null; then
        # $1 was not a full path but found on $PATH
        scriptpath="$(type -p "${scriptname}")"
        shellFuncFlag=false

    else
        # $1 not recognized
        printf '\nERROR: "%s" not found as a shell script nor recognized as a shell function. Aborting.\n\n' "${scriptpath}"
        return 1
    fi

    # DYNAMIC ANALYSIS - generates an accurate dependency list for the part of the script that is actually run

    # wrap running the script inside of a dummy function $fname() with a DEBUG trap 
    # that records everything that is run and saves it to files in $tmpdir
    
    fname="fun_${RANDOM}${RANDOM}"

    DEBUG_trap='type -p "${BASH_COMMAND%% *}" >>"'"${tmpdir}"'/'"${scriptname}"'.deps"; 
echo "${FUNCNAME:-"${BASH_SOURCE:-"$0"}"}:${LINENO}" >>"'"${tmpdir}"'/'"${scriptname}"'.coverage"; 
echo "${BASH_CMDS[@]}" >>"'"${tmpdir}"'/'"${scriptname}"'.cmds"; 
[[ "${DEBUG_declaredFunctionNames[*]}" == *"${FUNCNAME}"* ]] || { declare -F "${FUNCNAME}" &>/dev/null && { declare -f "${FUNCNAME}" 2>/dev/null >>"'"${tmpdir}"'/'"${scriptname}"'.funcs"; echo "${FUNCNAME}" >>"'"${tmpdir}"'/'"${scriptname}"'.funcnames"; DEBUG_declaredFunctionNames+=("${FUNCNAME}"); }; }'

    touch "${tmpdir}"/"${scriptname}".{deps,deps.guess,coverage,cmds,funcs,funcnames,xtrace}
    touch "${tmpdir}"/{deps.all,deps.guess.all}

    type -p bash >>"${tmpdir}"/"${scriptname}".deps

    hash -r

    source /proc/self/fd/0 <<EOF
${fname}() (
hash -r
BASH_XTRACEFD=\${fd_xtrace}
set -T
set -h
set -x
PS4=''
local -a DEBUG_declaredFunctionNames=("$fname")

$(${shellFuncFlag} && echo '. "'"${tmpdir}"'"/"'"${scriptname}"'".script.src')

trap '${DEBUG_trap}' DEBUG

$(<"${scriptpath}")

) {fd_xtrace}>"${tmpdir}"/"${scriptname}".xtrace $(${stdinFlag} && echo '0<&${fd_stdin}')
EOF

    # actually run the wrapper function we just made (send output to stderr)
    if ${stdinFlag}; then
        (${fname} "$@") {fd_stdin}<&0 >&2
    else
        (${fname} "$@") >&2
    fi

    trap -- DEBUG

    # source the functions the script recorded as having run and
    # "process" them by running them through declare -f ___ and
    # attempt to determine+record where they were sourced from 
    source "${tmpdir}"/"${scriptname}".funcs
    fname_def="$(declare -f "$fname")"
    while read -r; do
        declare -f "$REPLY" &>/dev/null && fname_def="${fname_def//"$(declare -f "$REPLY")"/}"
        funcsrc="$(declare -F "$REPLY")"
        funcsrc="${funcsrc#* }"
        funcsrc="${funcsrc#* }"
        echo "${funcsrc}" >>"${tmpdir}"/"${scriptname}".funcsrcs
    done <"${tmpdir}"/"${scriptname}".funcnames
    echo "${fname_def}" >>"${tmpdir}"/"${scriptname}".funcs
    source "${tmpdir}"/"${scriptname}".funcs

    # run lists of recorded commands and coverage through sort -u to remove duplicates
    echo "$(printf '%s\n' $(<"${tmpdir}"/"${scriptname}".cmds))" >"${tmpdir}"/"${scriptname}".cmds
    echo "$(printf '\n'; sort -u <"${tmpdir}"/"${scriptname}".cmds)" >"${tmpdir}"/"${scriptname}".cmds
    echo "$(sort -u <"${tmpdir}"/"${scriptname}".deps)" >"${tmpdir}"/"${scriptname}".deps
    cat "${tmpdir}"/"${scriptname}".cmds >>"${tmpdir}"/"${scriptname}".deps
    echo "$(sort -u <"${tmpdir}"/"${scriptname}".deps)" >"${tmpdir}"/"${scriptname}".deps
    echo "$(sort -t':' -k1,2 -V <"${tmpdir}"/"${scriptname}".coverage | uniq)" >"${tmpdir}"/"${scriptname}".coverage

    # STATIC ANALYSIS - makes a "best guess" for the dependencies of the rest of the script that wasnt actually executed
    
    # for each function ran (including the main wrapper function):
    #     load it (declare -f) into an array
    #     remove lines that were recorded as being run (leaving the missed / not-run / not-covered lines)
    #     split up remaining lines into seperate lines everywhere a new command is likely to be. e.g., after a '$('
    #     remove everything except the 1st word (representing the potential command run) from each line
    #     run that word through 'type -p' to see if there is a matching executable for it
    #     run final list through sort -u to remove duplicates
    while read -r funcname; do
        mapfile -t F < <(declare -f "$funcname")
        while read -r funcline; do
            F[$funcline]=''
        done < <(grep -F "${funcname}"':' <"${tmpdir}"/"${scriptname}".coverage | sed -E s/'^[^:]*\:'//)

        printf '%s\n' "${F[@]}" >"${tmpdir}"/"${scriptname}.${funcname}.coverage.missed"
        mapfile -t F < <(printf '%s\n' "${F[@]// +(['&|']) /$'\n'}")
        mapfile -t F < <(printf '%s\n' "${F[@]//['$<>']'('/$'\n'}")
        mapfile -t F < <(printf '%s\n' "${F[@]//@('eval'|'exec'|'if'|'elif')' '/$'\n'}" | sed -E 's/[[:space:]]+/ /g;s/^[[:space:]\(\{]*//;s/(\/usr\/?)?(\/bin\/?)?bash -c ["'"'"']*/\n/g;s/ .*$//;s/\;$//' | grep -E '[^[:space:]]+' | sort -u)
        type -p "${F[@]}" 2>/dev/null >>"${tmpdir}"/"${scriptname}".deps.guess
    done <"${tmpdir}"/"${scriptname}".funcnames

    mapfile -t F <"${tmpdir}"/"${scriptname}".deps.guess

    for kk in "${!F[@]}"; do
        grep -F -q "${F[$kk]}" <"${tmpdir}"/"${scriptname}".deps || echo "${F[$kk]}"
    done >"${tmpdir}"/"${scriptname}".deps.guess

    echo "$(sort -u <"${tmpdir}"/"${scriptname}".deps.guess)" >"${tmpdir}"/"${scriptname}".deps.guess

    # print dependencies and guessed dependencies for this script
    printf '\n\n----------------------------------------------------------------\n\nDEPENDENCIES DETERMINED FOR: %s\n\nDEPENDENCIES FOUND FROM EXECUTED CODE:\n%s\n' "$(${shellFuncFlag} && echo "${scriptname}" || echo "${scriptpath}")" "$(<"${tmpdir}"/"${scriptname}".deps)"

    [[ $(<"${tmpdir}"/"${scriptname}".deps.guess) ]] && printf '\n\nGUESSED DEPENDENCIES FROM "MISSED" CODE:\n\n%s\n' "$(<"${tmpdir}"/"${scriptname}".deps.guess)"

    # add dependencies to overall dependency lists
    cat "${tmpdir}"/"${scriptname}".deps >>"${tmpdir}"/deps.all
    cat "${tmpdir}"/"${scriptname}".deps.guess >>"${tmpdir}"/deps.guess.all

    # check depencency lists for any shell scripts (unfortunately the DEBUG trap wont automatically propogate to these, only to shell functions)
    # for any shell script dependencies found, search xtrace record for specific invocations and run all those through getdeps.
    # unfortunately, this doesnt work for guessed depoenbdencies that are shell scripts - for those increse code coverage and re-run

    mapfile -t mdeps < <(file -f "${tmpdir}"/"${scriptname}".deps | grep ASCII | sed -E s/'\:[[:space:]]+.*$'// | while read -r; do grep -F "${REPLY}" <"${tmpdir}"/"${scriptname}".xtrace | grep -v 'type -p'; done | sort -u)
    mapfile -t fdeps < <(file -f "${tmpdir}"/"${scriptname}".deps.guess | grep ASCII | sed -E s/'\:[[:space:]]+.*$'//)

    if ((${#mdeps[@]} > 0)); then
        for kk in "${!mdeps[@]}"; do
            getdeps ${mdeps[$kk]}
        done
    else
        printAllDepsFlag=false
    fi
        
    # print final overall dependency list and guessed dependency lists, if needed
    ${printAllDepsFlag} && {
        printf '\n\n----------------------------------------------------------------\n\nDEPENDENCIES DETERMINED FOR %s AND ALL DEPENDENT SCRIPTS CALLED BY IT\n\nDEPENDENCIES FOUND FROM EXECUTED CODE:\n\n%s\n' "$(${shellFuncFlag} && echo "${scriptname}" || echo "${scriptpath}")" "$(sort -u <"${tmpdir}"/deps.all | grep -E '.+')"

        [[ $(<"${tmpdir}"/deps.guess.all) ]] && printf '\n\nALL GUESSED DEPENDENCIES FROM "MISSED" CODE:\n\n%s\n' "$(sort -u <"${tmpdir}"/deps.guess.all | grep -E '.+')"

        }

    # print warning about missed dependency is guessed depedent shell scripts
    ((${#fdeps[@]} > 0)) && printf '\n\n----------------------------------------------------------------\n\nWARNING: THE FOLLOWING SHELL SCRIPTS ARE INCLUDED IN THE "GUESSED DEPENDENCIES" FROM ANALYSING CODE THAT WAS NOT EXECUTED:\N%s\n\nTHESE HAVE NOT BEEN RECURSVELY CHECKED FOR THEIR OWN DEPENDENCIES.\nAS SUCH, THE LIST OF DEPENDENCIES MAY BE INCOMPLETE.\nTO GET A MORE COMPLETE LIST, INCREASE CODE COVERAGE AND ENSURE THESE SHELL SCRIPTS ARE EXECUTED.\n\n' "${fdeps[*]}"

    # print tmpdir path where saved dependency lists are kept
    ${printAllDepsFlag} && printf '\n\n----------------------------------------------------------------\n\nMORE DETAILED INFORMATION related to dependencies and coverage can be found under: %s\n\n' "${tmpdir}"

)
