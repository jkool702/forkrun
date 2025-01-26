#!/bin/bash

testDir='/usr'
ramdiskMnt='c/mnt/ramdisk'
#useRamdiskFlag=true

################################################################################

: "${testDir:=/usr}" "${useRamdiskFlag:=true}"

[[ ${useRamdiskFlag} == 'false' ]] || useRamdiskFlag=true
[[ -d "${testDir}" ]] || { printf '\n\nERROR: can not access "%s". Perhaps due to permissions issues?\n\nABORTING\n\n' "${testDir}"; exit 1; }

#unset forkrun
declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source  ./forkrun.bash; }
declare -F forkrun &>/dev/null || source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)

type nproc &>/dev/null && nProcs=$(nproc) || nProcs=8

numArgsA=($(( ${nProcs} - 2 )) $(( ${nProcs} + 2 )) $(( ${nProcs} * 128 )) $(( ${nProcs} * 1024 + 1 )))
#numArgsA=($(( ${nProcs} - 2 )) $(( ${nProcs} + 2 )))
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


{

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

            cat >&2 <<<\(\ \{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur\ 2\>/dev/null\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(cat\ "${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ "${runArgs//%s/%s\\}"\ \'\;\ \}\ \|\ tee\ -a\ /tmp/.forkrun.log\;\ \)$'\n'
            source /proc/self/fd/0 <<<\(\ \{\ diff\ \&\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur\ 2\>/dev/null\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(cat\ "${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ "${runArgs//%s/%s\\}"\ \'\;\ \}\ \|\ tee\ -a\ /tmp/.forkrun.log\;\ \)$'\n'
            cat >&2 <<<\(\ \{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur0\ 2\>/dev/null\ -z\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(tr\ "'"\\0"'"\ "'"\\n"'"\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur0\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ -z\ "${runArgs//%s/%s\\}"\ \'\;\ \}\ \|\ tee\ -a\ /tmp/.forkrun.log\;\ \)$'\n'
            source /proc/self/fd/0 <<<\(\ \{\ diff\ \&\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur0\ 2\>/dev/null\ -z\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(tr\ "'"\\0"'"\ "'"\\n"'"\ \<"${ramdiskMnt}"/forkrun_unit-tests_data/filelistCur0\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ -z\ "${runArgs//%s/%s\\}"\ \'\;\ \}\ \|\ tee\ -a\ /tmp/.forkrun.log\;\ \)$'\n'
       done
    done
done

} | tee >(grep -E '^FAIL' >>"${ramdiskMnt}/forkrun_unit-tests_data/fail.log")

[[ -f "${ramdiskMnt}/forkrun_unit-tests_data/fail.log" ]] && [[ $(<"${ramdiskMnt}/forkrun_unit-tests_data/fail.log") ]] && {
    printf '\n\n--------------------------------------------------------------\n\nFAILED TESTS:\n\n'
    cat "${ramdiskMnt}/forkrun_unit-tests_data/fail.log"
}
