#!/usr/bin/env bash

getdeps() (
	## analyzes a shell script to determine its dependencies

	shopt -s extglob
	shopt -s extdebug

	local DEBUG_trap cfun printAllDepsFlag scriptpath scriptname fname tmpdir shellFuncFlag stdinFlag
	local -a F

	cfun="$(caller 0)"
	cfun="${cfun#* }"
	cfun="${cfun% *}"

	if [[ "$cfun" == 'getdeps' ]]; then
		printAllDepsFlag=false
	else
		printAllDepsFlag=false
	fi

	scriptpath="$1"

	scriptname="${scriptpath##*\/}"
	scriptname="${scriptname//+([[:space:]])/_}"
	scriptname="${scriptname//+([^[:print:]])/}"

	shift 1

	[ -t 0 ] && stdinFlag=false || stdinFlag=true

	tmpdir="$(mktemp -d -t getdeps.XXXXXX)"

	if [[ -f "${scriptpath}" ]]; then
		type -p realpath &>/dev/null && scriptpath="$(realpath "${scriptpath}")"
		shellFuncFlag=false

	elif declare -F "${scriptname}" &>/dev/null; then
		declare -f "${scriptname}" >"${tmpdir}"/"${scriptname}".script.src
		cat <<EOF >"${tmpdir}"/"${scriptname}".script
$(${stdinFlag} && printf 'cat |') ${scriptname} "\${@}" $(${stdinFlag})
EOF
		scriptpath="${tmpdir}"/"${scriptname}".script
		chmod +x "${scriptpath}"
		shellFuncFlag=true

	elif type -p "${scriptname}" &>/dev/null; then
		scriptpath="$(type -p "${scriptname}")"
		shellFuncFlag=false

	else
		printf '\nERROR: %s not found nor recognized as a shell function. Aborting.\n\n'
		return 1
	fi

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

	if ${stdinFlag}; then
		(${fname} "$@") {fd_stdin}<&0
	else
		(${fname} "$@")
	fi

	trap -- DEBUG

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

	{
		printf '\n'
		printf '%s\n' $(<"${tmpdir}"/"${scriptname}".cmds) | sort -u
	} >>"${tmpdir}"/"${scriptname}".deps
	echo "$(sort -u <"${tmpdir}"/"${scriptname}".deps)" >"${tmpdir}"/"${scriptname}".deps
	echo "$(sort -t':' -k1,2 -V <"${tmpdir}"/"${scriptname}".coverage | uniq)" >"${tmpdir}"/"${scriptname}".coverage

	source "${tmpdir}"/"${scriptname}".funcs

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

	printf '\n\nDEPENDENCIES DETERMINED FOR: %s\n\nDEPENDENCIES FOUND FROM EXECUTED CODE:\n%s\n' "$(${shellFuncFlag} && echo "${scriptname}" || echo "${scriptpath}")" "$(<"${tmpdir}"/"${scriptname}".deps)"

	[[ $(<"${tmpdir}"/"${scriptname}".deps.guess) ]] && printf '\nGUESSED DEPENDENCIES FROM "MISSED" CODE:\n%s\n' "$(<"${tmpdir}"/"${scriptname}".deps.guess)"

	cat "${tmpdir}"/"${scriptname}".deps >>"${tmpdir}"/deps.all
	cat "${tmpdir}"/"${scriptname}".deps.guess >>"${tmpdir}"/deps.guess.all

	mapfile -t mdeps < <(file -f "${tmpdir}"/"${scriptname}".deps | grep ASCII | sed -E s/'\:[[:space:]]+.*$'// | while read -r; do grep -F "${REPLY}" <"${tmpdir}"/"${scriptname}".xtrace | grep -v 'type -p'; done)
	mapfile -t fdeps < <(file -f "${tmpdir}"/"${scriptname}".deps.guess | grep ASCII | sed -E s/'\:[[:space:]]+.*$'//)

	((${#mdeps[@]} > 0)) && for kk in "${!mdeps[@]}"; do
		getdeps ${mdeps[$kk]}
		${printAllDepsFlag} && {
			printf '\n\nDEPENDENCIES DETERMINED FOR %s AND ALL DEPENDENT SCRIPTS CALLED BY IT\n\nDEPENDENCIES FOUND FROM EXECUTED CODE:\n%s\n' "$(${shellFuncFlag} && echo "${scriptname}" || echo "${scriptpath}")" "$(<"${tmpdir}"/deps.all)"

			[[ $(<"${tmpdir}"/deps.guess.all) ]] && printf '\nALL GUESSED DEPENDENCIES FROM "MISSED" CODE:\n%s\n' "$(<"${tmpdir}"/deps.guess.all)"

		}
	done

	((${#fdeps[@]} > 0)) && printf '\nWARNING: THE FOLLOWING SHELL SCRIPTS ARE INCLUDED IN THE "GUESSED DEPENDENCIES" FROM ANALYSING CODE THAT WAS NOT EXECUTED:\N%s\n\nTHESE HAVE NOT BEEN RECURSVELY CHECKED FOR THEIR OWN DEPENDENCIES.\nAS SUCH, THE LIST OF DEPENDENCIES MAY BE INCOMPLETE.\nTO GET A MORE COMPLETE LIST, INCREASE CODE COVERAGE AND ENSURE THESE SHELL SCRIPTS ARE EXECUTED.\n\n' "${fdeps[*]}"

	printf '\nINFORMATION related to dependencies and coverage can be found under: %s\n\n' "${tmpdir}"

)
