#!/bin/bash

#testDir='/usr'
#ramdiskMnt='/mnt/ramdisk'
#useRamdiskFlag=true

################################################################################

: "${testDir:=/usr}" "${useRamdiskFlag:=true}" "${ramdiskMnt:=/mnt/ramdisk}"

[[ ${useRamdiskFlag} == 'false' ]] || useRamdiskFlag=true
[[ -d "${testDir}" ]] || { printf '\n\nERROR: can not access "%s". Perhaps due to permissions issues?\n\nABORTING\n\n' "${testDir}"; exit 1; }

#unset forkrun
declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source  ./forkrun.bash; }
declare -F forkrun &>/dev/null || source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)

type nproc &>/dev/null && nProcs=$(nproc) || nProcs=8

numArgsA=( $(( ${nProcs} - 2 )) $(( 8 * ${nProcs} + 2 )) $(( 64 * ${nProcs} + 8 )) )
mapfile -t numArgsA < <(printf '%s\n' "${numArgsA[@]}" | sort -u -n)

testDir="${testDir%/}"
ramdiskMnt="${ramdiskMnt%/}"

mkdir -p  "${ramdiskMnt}"

${useRamdiskFlag} && {
    grep -qF 'tmpfs '"${ramdiskMnt}" </proc/mounts || {
        [[ "$USER" == 'root' ]] && mount -t tmpfs tmpfs "${ramdiskMnt}" || useRamdiskFlag=false
    }
}

mkdir -p  "${ramdiskMnt}"/forkrun_unit-tests_data

if ${useRamdiskFlag}; then
    mkdir -p  "${ramdiskMnt}"/forkrun_unit-tests_data/"${testDir##*/}"
    find "${testDir}" -type f -size -$((1<<20)) -print0 | head -z -n "${numArgsA[-1]}" | rsync -a --from0 --files-from=- / "${ramdiskMnt}"/forkrun_unit-tests_data/"${testDir##*/}"
    find "${ramdiskMnt}"/forkrun_unit-tests_data/"${testDir##*/}" -type f -print0 > "${ramdiskMnt}"/forkrun_unit-tests_data/filelist0
else
    find "${testDir}" -type f -print0 > "${ramdiskMnt}"/forkrun_unit-tests_data/filelist0
fi

[[ -f "${ramdiskMnt}/forkrun_unit-tests_data/fail.log" ]] && { 
    cat "${ramdiskMnt}/forkrun_unit-tests_data/fail.log" >> "${ramdiskMnt}/forkrun_unit-tests_data/fail.log.old" && \rm "${ramdiskMnt}/forkrun_unit-tests_data/fail.log"
}

fStr=('printf '"'"'%s\n'"'" sha1sum sha256sum)
kStr=('' '-k')
nStr=('' '-n <#>')

kFix=(' | sort' '')
fFix=('' '| sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//' '| sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//')

declare -i nPass=0 nFail=0

{ :; } {fd_stats}<><(:)


_trap_exit () {
    read -r -u ${fd_stats} nPass nFail &>/dev/null || return
    (( nPass > 0 )) || (( nFail > 0 )) || return
    exec {fd_stats}>&-
    printf '\n\n--------------------------------------------------------------\n\nUNIT TESTING HAS FINISHED!!!\n\nPASS:   %s tests\nFAIL:   %s tests\n\n' "${nPass}" "${nFail}"
    [[ -f "${ramdiskMnt}/forkrun_unit-tests_data/fail.log" ]] && [[ $(<"${ramdiskMnt}/forkrun_unit-tests_data/fail.log") ]] && {
        printf '\n\n--------------------------------------------------------------\nFAILED TESTS:\n\n'
        cat "${ramdiskMnt}/forkrun_unit-tests_data/fail.log"
    }
    trap - INT TERM HUP EXIT
}

trap '_trap_exit' INT TERM HUP EXIT

{

    trap 'printf '"'"'%s %s\n'"'"' "${nPass}" "${nFail}" >&${fd_stats}; trap - INT TERM HUP EXIT' INT TERM HUP EXIT

    for nArgs in "${numArgsA[@]}"; do
        printf  '\n\n--------------------------------------------------\nBEGINNING TEST CASE FOR STDIN LENGTH = %s\n\n' "${nArgs}"
        nFix=('' ' | head -n '"$((nArgs-7))")

        for fInd in "${!fStr[@]}"; do 
           
            shuf -z -n ${nArgs} <"${ramdiskMnt}"/forkrun_unit-tests_data/filelist0 | tr '\0' '\n'  >"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur
            shuf -z -n ${nArgs} <"${ramdiskMnt}"/forkrun_unit-tests_data/filelist0  >"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur0

            runArgsA=()
            mapfile -t runArgsA < <(echo {-k\ ,}{-j\ 27\ ,-j\ -\ ,}{-l\ 1\ ,-L\ 1\ ,}{-n\ $((nArgs-7))\ ,}{-t\ \/tmp\ ,}{-D\ ,}{"${fStr[$fInd]}"\ ,--\ "${fStr[$fInd]}"\ ,-i\ "${fStr[$fInd]}"\ \{\}\ ,-i\ --\ "${fStr[$fInd]}"\ \{\}\ }$'\n')
            runArgsA=("${runArgsA[@]# }")
            for runArgs in "${runArgsA[@]}"; do

                [[ "${runArgs}" == '-k'* ]] && kInd=1 || kInd=0
                [[ "${runArgs}" == *'-n '[0-9]* ]] && nInd=1 || nInd=0

                           cat >&2 <<<\{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur\ 2\>/dev/null\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(cat\ "${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ \{\ \(\(nPass\+\+\)\)\;\ printf\ \'%s\'\ \"PASS\"\;\ \}\ \|\|\ \{\ \(\(nFail\+\+\)\)\;\ printf\ \'%s\'\ \"FAIL\"\;\ \}\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ "${runArgs//"'"/"'"'"'"'"'"'"'"}"\ \'\;\ \}\;$'\n'
           source /proc/self/fd/0 <<<\{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur\ 2\>/dev/null\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(cat\ "${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ \{\ \(\(nPass\+\+\)\)\;\ printf\ \'%s\'\ \"PASS\"\;\ \}\ \|\|\ \{\ \(\(nFail\+\+\)\)\;\ printf\ \'%s\'\ \"FAIL\"\;\ \}\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ "${runArgs//"'"/"'"'"'"'"'"'"'"}"\ \'\;\ \}\;$'\n'
                          cat >&2 <<<\{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur0\ 2\>/dev/null\ -z\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(tr\ "'"\\0"'"\ "'"\\n"'"\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur0\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ \{\ \(\(nPass\+\+\)\)\;\ printf\ \'%s\'\ \"PASS\"\;\ \}\ \|\|\ \{\ \(\(nFail\+\+\)\)\;\ printf\ \'%s\'\ \"FAIL\"\;\ \}\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ -z\ "${runArgs//"'"/"'"'"'"'"'"'"'"}"\ \'\;\ \}\;$'\n'
          source /proc/self/fd/0  <<<\{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur0\ 2\>/dev/null\ -z\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(tr\ "'"\\0"'"\ "'"\\n"'"\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur0\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ \{\ \(\(nPass\+\+\)\)\;\ printf\ \'%s\'\ \"PASS\"\;\ \}\ \|\|\ \{\ \(\(nFail\+\+\)\)\;\ printf\ \'%s\'\ \"FAIL\"\;\ \}\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ -z\ "${runArgs//"'"/"'"'"'"'"'"'"'"}"\ \'\;\ \}\;$'\n'
            done
            printf 'nPass=%s   nFail=%s\n' $nPass $nFail >&2
        done
    done

    trap - INT TERM HUP EXIT
    printf '%s %s\n' "${nPass}" "${nFail}" >&${fd_stats}; 

} | tee >(grep -E '^FAIL' >>"${ramdiskMnt}/forkrun_unit-tests_data/fail.log")

trap - INT TERM HUP EXIT
_trap_exit 
