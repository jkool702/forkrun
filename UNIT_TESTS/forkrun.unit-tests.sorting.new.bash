#!/bin/bash

#testDir='/usr'
useRamdiskFlag=true

################################################################################

: "${testDir:=/usr}" "${useRamdiskFlag:=false}"

[[ ${useRamdiskFlag} == 'true' ]] || useRamdiskFlag=false
[[ -d "${testDir}" ]] || { printf '\n\nERROR: can not access "%s". Perhaps due to permissions issues?\n\nABORTING\n\n' "${testDir}"; exit 1; }

#unset forkrun
declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source  ./forkrun.bash; }
declare -F forkrun &>/dev/null || source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)
declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source ./forkrun.bash; }

type nproc 1>/dev/null 2>/dev/null && nProcs=$(nproc) || nProcs=8

mkdir -p /mnt/ramdisk/forkrun_unit-tests_data

if ${useRamdiskFlag}; then
    mkdir -p /mnt/ramdisk/
    grep -qF '/mnt/ramdisk' </proc/mounts || mount -t tmpfs tmpfs /mnt/ramdisk

    rsync -a --max-size=$((1<<20)) "${testDir}" /mnt/ramdisk/forkrun_unit-tests_data

    find /mnt/ramdisk/forkrun_unit-tests_data -type f -print0 > /mnt/ramdisk/forkrun_unit-tests_data/filelist0
else
    find "${testDir}" -type f -print0 > /mnt/ramdisk/forkrun_unit-tests_data/filelist0
fi

fStr=('printf '"'"'%s\n'"'" sha1sum sha256sum)
kStr=('' '-k')

kFix=('| sort' '')
fFix=('' '| sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//' '| sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//')


for nArgs in $(( ${nProcs} - 2 )) $(( ${nProcs} + 2 )) $(( ${nProcs} * 128 )) $(( ${nProcs} * 1024 )); do
    printf  '\n\n--------------------------------------------------\nBEGINNING TEST CASE FOR STDIN LENGTH = %s\n\n' "${nArgs}"

    for fInd in 0 1 2; do 
       
        shuf -z -n ${nArgs} </mnt/ramdisk/forkrun_unit-tests_data/filelist0 | tr '\0' '\n'  >/mnt/ramdisk/forkrun_unit-tests_data/filelistCur
        shuf -z -n ${nArgs} </mnt/ramdisk/forkrun_unit-tests_data/filelist0  >/mnt/ramdisk/forkrun_unit-tests_data/filelistCur0

        runArgsA=()
        mapfile -t runArgsA < <(echo {-k\ ,}{-j\ 27\ ,-j\ -\ ,}{-l\ 1\ ,}{-t\ \/tmp\ ,}{-D\ ,}{"${fStr[$fInd]}"\ ,--\ "${fStr[$fInd]}"\ ,-i\ "${fStr[$fInd]}"\ \{\}\ ,-i\ --\ "${fStr[$fInd]}"\ \{\}\ }$'\n')
        runArgsA=("${runArgsA[@]# }")
        for runArgs in "${runArgsA[@]}"; do

            [[ "${runArgs}" == '-k'* ]] && kInd=1 || kInd=0

	    source /proc/self/fd/0 <<<\(\ \{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \</mnt/ramdisk/forkrun_unit-tests_data/filelistCur\ 2\>/dev/null\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(cat\ /mnt/ramdisk/forkrun_unit-tests_data/filelistCur\ "${kFix[$kInd]}"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ "${runArgs//%s/%s\\}"\ \'\;\ \}\ \|\ tee\ -a\ /tmp/.forkrun.log\;\ \)$'\n'

	    source /proc/self/fd/0 <<<\(\ \{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(forkrun\ \</mnt/ramdisk/forkrun_unit-tests_data/filelistCur0\ 2\>/dev/null\ -z\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(tr\ "'"\\0"'"\ "'"\\n"'"\ \</mnt/ramdisk/forkrun_unit-tests_data/filelistCur0\ "${kFix[$kInd]}"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf\ \'\:\ %s\\n\'\ \'\ forkrun\ -z\ "${runArgs//%s/%s\\}"\ \'\;\ \}\ \|\ tee\ -a\ /tmp/.forkrun.log\;\ \)$'\n'
        done
    done
done

