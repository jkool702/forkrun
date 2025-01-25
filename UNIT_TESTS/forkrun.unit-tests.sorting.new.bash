#!/bin/bash

testDir='/mnt/ramdisk/forkrun_unit-tests_data/usr'
#useRamdiskFlag=true

################################################################################

: "${testDir:=/usr}" "${useRamdiskFlag:=false}"

[[ ${useRamdiskFlag} == 'true' ]] || useRamdiskFlag=false
[[ -d "${testDir}" ]] || { printf '\n\nERROR: can not access "%s". Perhaps due to permissions issues?\n\nABORTING\n\n' "${testDir}"; exit 1; }

#unset forkrun
declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source  ./forkrun.bash; }
declare -F forkrun &>/dev/null || source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)

type nproc &>/dev/null && nProcs=$(nproc) || nProcs=8

mkdir -p /mnt/ramdisk/forkrun_unit-tests_data

 ${useRamdiskFlag} && {
     [[ "$USER" == 'root' ]] && ramdiskMnt='/mnt/ramdisk' || useRamdiskFlag=false
}

if ${useRamdiskFlag}; then
    mkdir -p "${ramdiskMnt}"
    grep -qF 'tmpfs '"${ramdiskMnt}" </proc/mounts || mount -t tmpfs tmpfs /mnt/ramdisk

    rsync -a --max-size=$((1<<20)) "${testDir}" /mnt/ramdisk/forkrun_unit-tests_data

    find /mnt/ramdisk/forkrun_unit-tests_data -type f -print0 > /mnt/ramdisk/forkrun_unit-tests_data/filelist0
else
    find "${testDir}" -type f -print0 > /mnt/ramdisk/forkrun_unit-tests_data/filelist0
fi

[[ -f "/mnt/ramdisk/forkrun_unit-tests_data/fail.log" ]] && { 
    cat "/mnt/ramdisk/forkrun_unit-tests_data/fail.log" >> "/mnt/ramdisk/forkrun_unit-tests_data/fail.log.old" && \rm "/mnt/ramdisk/forkrun_unit-tests_data/fail.log"
}

fStr=('printf '"'"'%s\n'"'" sha1sum sha256sum)
kStr=('' '-k')
nStr=('' '-n <#>')

kFix=(' | sort' '')
fFix=('' '| sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//' '| sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//')

#numArgsA=($(( ${nProcs} - 2 )) $(( ${nProcs} + 2 )) $(( ${nProcs} * 128 )) $(( ${nProcs} * 1024 + 1 )))
numArgsA=($(( ${nProcs} - 2 )) $(( ${nProcs} + 2 )))

{

for nArgs in "${numArgsA[@]}"; do
    printf  '\n\n--------------------------------------------------\nBEGINNING TEST CASE FOR STDIN LENGTH = %s\n\n' "${nArgs}"
    nFix=('' ' | head -n '"$((nArgs-7))")

    for fInd in "${!fStr[@]}"; do 
       
        shuf -z -n ${nArgs} </mnt/ramdisk/forkrun_unit-tests_data/filelist0 | tr '\0' '\n'  >/mnt/ramdisk/forkrun_unit-tests_data/filelistCur
        shuf -z -n ${nArgs} </mnt/ramdisk/forkrun_unit-tests_data/filelist0  >/mnt/ramdisk/forkrun_unit-tests_data/filelistCur0

        runArgsA=()
        mapfile -t runArgsA < <(echo {-k\ ,}{-j\ 27\ ,-j\ -\ ,}{-l\ 1\ ,-L\ 1\ ,}{-n\ $((nArgs-7))\ ,}{-t\ \/tmp\ ,}{-D\ ,}{"${fStr[$fInd]}"\ ,--\ "${fStr[$fInd]}"\ ,-i\ "${fStr[$fInd]}"\ \{\}\ ,-i\ --\ "${fStr[$fInd]}"\ \{\}\ }$'\n')
        runArgsA=("${runArgsA[@]# }")
        for runArgs in "${runArgsA[@]}"; do

            [[ "${runArgs}" == '-k'* ]] && kInd=1 || kInd=0
            [[ "${runArgs}" == *'-n '[0-9]* ]] && nInd=1 || nInd=0

	        cat >&2 <<<\(\ \{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \</mnt/ramdisk/forkrun_unit-tests_data/filelistCur\ 2\>/dev/null\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(cat\ /mnt/ramdisk/forkrun_unit-tests_data/filelistCur\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ "${runArgs//%s/%s\\}"\ \'\;\ \}\ \|\ tee\ -a\ /tmp/.forkrun.log\;\ \)$'\n'
            source /proc/self/fd/0 <<<\(\ \{\ diff\ \&\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \</mnt/ramdisk/forkrun_unit-tests_data/filelistCur\ 2\>/dev/null\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(cat\ /mnt/ramdisk/forkrun_unit-tests_data/filelistCur\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ "${runArgs//%s/%s\\}"\ \'\;\ \}\ \|\ tee\ -a\ /tmp/.forkrun.log\;\ \)$'\n'
	        cat >&2 <<<\(\ \{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \</mnt/ramdisk/forkrun_unit-tests_data/filelistCur0\ 2\>/dev/null\ -z\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(tr\ "'"\\0"'"\ "'"\\n"'"\ \</mnt/ramdisk/forkrun_unit-tests_data/filelistCur0\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ -z\ "${runArgs//%s/%s\\}"\ \'\;\ \}\ \|\ tee\ -a\ /tmp/.forkrun.log\;\ \)$'\n'
            source /proc/self/fd/0 <<<\(\ \{\ diff\ \&\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \</mnt/ramdisk/forkrun_unit-tests_data/filelistCur0\ 2\>/dev/null\ -z\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(tr\ "'"\\0"'"\ "'"\\n"'"\ \</mnt/ramdisk/forkrun_unit-tests_data/filelistCur0\ "${nFix[$nInd]}"\ "${kFix[$kInd]}"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ -z\ "${runArgs//%s/%s\\}"\ \'\;\ \}\ \|\ tee\ -a\ /tmp/.forkrun.log\;\ \)$'\n'
       done
    done
done

} | tee >(grep -E '^FAIL' >>"/mnt/ramdisk/forkrun_unit-tests_data/fail.log")

[[ -f "/mnt/ramdisk/forkrun_unit-tests_data/fail.log" ]] && {
    printf '\n\n--------------------------------------------------------------\n\nFAILED TESTS:\n\n'
    cat "/mnt/ramdisk/forkrun_unit-tests_data/fail.log"
}