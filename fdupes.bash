#!/usr/bin/env bash

fdupes() {
    # quickly finds duplicate files using "forkrun" the cksum hash 
    #
    # inputs are directories to look for duplicate files under
    #
    # inputs starting with `!` will be excluded from this search
    #
    # if you want to look for duplicates under a directory starting 
    # with a '!' use the full path (e.g. '/tmp/!whyyyy')

    # source forkrun
    declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source ./forkrun.bash; } || { type -p forkrun.bash &>/dev/null && source "$(type -p forkrun.bash )"; } || source <(curl 'https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash') || { printf '\nERROR!!! The forkrun function is not defined and its source code could not be found/downloaded. ABORTING!\n\n'; return 1; }

    local excludeStr fdTmpDirRoot fdTmpDir nn
    local -a searchA excludeA

    for nn in "$@"; do
    	if [[ "${nn}" == '!'* ]]; then
    		excludeA+=("${nn#'!'}")
    	else
    		searchA+=("${nn}")
    	fi
    done

    [[ ${fdTmpDirRoot} ]] || { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && fdTmpDirRoot="${TMPDIR}"; } || { [[ -d '/dev/shm' ]] && fdTmpDirRoot='/dev/shm'; }  || { [[ -d '/tmp' ]] && fdTmpDirRoot='/tmp'; } || fdTmpDirRoot="$(pwd)"
    fdTmpDir="$(mktemp -p "${fdTmpDirRoot}" -d .fdupes.XXXXXX)"

    trap '\rm -rf "${fdTmpDir:?}"' EXIT

    mkdir -p "${fdTmpDir}"/{size,hash}/{data,dupes}

    fdupes_size() {
    	set -C
    	IFS=$'\n'

    	local -a fSizeA fNameA
    	local -i kk

    	mapfile -t fSizeA < <(du "${@}")
    	mapfile -t fNameA <<<"${fSizeA[*]#*$'\t'}"
    	mapfile -t fSizeA <<<"${fSizeA[*]%%$'\t'*}"

    	for kk in "${!fSizeA[@]}"; do
    		echo "${fNameA[$kk]}" >"${fdTmpDir}/size/data/${fSizeA[$kk]}" || {
    			echo "${fNameA[$kk]}" >>"${fdTmpDir}/size/data/${fSizeA[$kk]}" 
    			: >"${fdTmpDir}/size/dupes/${fSizeA[$kk]}"
    		}
    	done &>/dev/null

    }
    fdupes_hash() {
    	set -C
    	IFS=$'\n'

    	local -a fHashA fNameA
    	local -i kk

    	mapfile -t fHashA < <(cksum "${@}")
    	mapfile -t fHashA <<<"${fHashA[*]/ /_}"
    	mapfile -t fNameA <<<"${fHashA[*]#* }"
    	mapfile -t fHashA <<<"${fHashA[*]%% *}"

    	for kk in "${!fHashA[@]}"; do
    		echo "${fNameA[$kk]}" >"${fdTmpDir}/hash/data/${fHashA[$kk]}" || {
    			echo "${fNameA[$kk]}" >>"${fdTmpDir}/hash/data/${fHashA[$kk]}" 
    			: >"${fdTmpDir}/hash/dupes/${fHashA[$kk]}"
    		}
    	done &>/dev/null

    }

    #declare -f fdupes_size fdupes_hash
    #echo "tmpDir = ${fdTmpDir}"

    printf -v excludeStr ' -path '"'"'%s'"'"' -prune -o ' "${excludeA[@]}"

    source /proc/self/fd/0 <<<"find \"\${searchA[@]}\" ${excludeStr} -type f -print" | forkrun fdupes_size

	mapfile -t dupes_size < <(printf '%s\n' "${fdTmpDir}"/size/dupes/*)
	mapfile -t dupes_size <<<"${dupes_size//'/size/dupes/'/'/size/data/'}"

	[[ ${#dupes_size} == 0 ]] || cat "${dupes_size[@]}" | forkrun fdupes_hash


	[[ $(echo "${fdTmpDir}"/hash/dupes/*) ]] && {
		printf '\nDUPLICATES FOUND!!!\n\n'
		for nn in "${fdTmpDir}"/hash/dupes/*; do
			nnCur="${nn##*/}"
			nnCur="${nnCur/_/ }"
			printf '\nCKSUM HASH: %s\n%s\n\n' "${nnCur}" "$(<""${fdTmpDir}"/hash/data/${nn##*/}")"
		done
	}
}
