#!/bin/bash

#testDir='/usr'
useRamdiskFlag=true

################################################################################

: "${testDir:=/usr}" "${useRamdiskFlag:=false}"

[[ ${useRamdiskFlag} == 'true' ]] || useRamdiskFlag=false
[[ -d "${testDir}" ]] || { printf '\n\nERROR: can not access "%s". Perhaps due to permissions issues?\n\nABORTING\n\n' "${testDir}"; exit 1; }

unset forkrun
{ [[ -f ./forkrun.bash ]] && source  ./forkrun.bash; }
declare -F forkrun &>/dev/null || source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)
declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source ./forkrun.bash; }

which nproc 1>/dev/null 2>/dev/null && nProcs=$(nproc) || nProcs=8

if ${useRamdiskFlag}; then
	mkdir -p /mnt/ramdisk/
	cat /proc/mounts | grep -F '/mnt/ramdisk' || mount -t tmpfs tmpfs /mnt/ramdisk

    mkdir -p /mnt/ramdisk/forkrun_unit-tests_data
	rsync -a --max-size=$((2<<20)) "${testDir}" /mnt/ramdisk/forkrun_unit-tests_data

	mapfile -t -d '' A < <(find /mnt/ramdisk/forkrun_unit-tests_data -type f -print0)
else
	mapfile -t -d '' A < <(find "${testDir}" -type f -print0)
fi

fStr=('printf '"'"'%\n'"'" sha1sum sha256sum)
kStr=('' '-k')

kFix=('| sort' '')
fFix=('' '| sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//' '| sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//')

mapfile -t runArgsA < <(echo {-k\ ,}{-j\ 27\ ,}{-l\ 1\ ,}{-t\ \/tmp\ ,}{-D\ ,}{"${fStr[$fInd]}"\ ,--\ "${fStr[$fInd]}"\ ,-i\ "${fStr[$fInd]}"\ \{\}\ ,-i\ --\ "${fStr[$fInd]}"\ \{\}\ }$'\n')

for nArgs in $(( ${nProcs} * 1024 )) $(( ${nProcs} * 128 )) $(( ${nProcs} + 2 )) $(( ${nProcs} - 2 )); do
	for fInd in 0 1 2; do 
		for runArgs in "${runArgsA[@]}"; do

			[[ "${runArgs}" == '-k'* ]] && kInd=1 || kInd=0

			source <(printf '%s' \(\ mapfile\ -t\ C\ \<\(IFS=\$\'\\n\'\;\ shuf\ -n\ ${nArgs}\ \<\<\<\"\$\{A\[\*\]\}\"\)\;\ \{\ diff\ 2\>/dev/null\ -q\ -B\ -E\ -Z\ -d\ -a\ -b\ -w\ \<\(printf\ \'%s\\n\'\ \"\$\{C\[@\]\}\"\ \|\ forkrun\ 2\>/dev/null\ "${runArgs}"\ "${fFix[$fInd]}"\ "${kFix[$kInd]}"\ \)\ \<\(printf\ \'%s\\n\'\ \"\$\{C\[@\]\}\"\)\ \&\&\ printf\ \'%s\'\ \"PASS\"\ \|\|\ printf\ \'%s\'\ \"FAIL\"\;\ printf \': %s\\n\'\ \'printf\ \'\"\'\"\'%s\\n\'\"\'\"\ \"\$\{C\[@\]\}\"\ \|\ forkrun\ 2\>/dev/null\ "${runArgs}"\;\ \}\ \|\ tee -a /tmp/.forkrun.log\;\ \)$'\n';)

		done
	done
done
