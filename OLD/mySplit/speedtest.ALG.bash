#!/usr/bion/env bash

shopt -s extglob

myTimeDiff() {
    local Td
    T1=${EPOCHREALTIME}

    [[ ${nRep} ]] || local nRep=1
    Td=$(( ( ${T1//./} - ${1//./} ) / ${nRep} ))
    echo "${Td:0:$(( ${#Td} - 6 ))}.$(printf '%0.6d' "${Td: -6}")"
}
    
tests=(sha1sum sha256sum sha512sum sha224sum sha384sum md5sum 'sum -s' 'sum -r' cksum b2sum 'cksum -a sm3')

declare -F mySplit 1>/dev/null 2>&1 || { [[ -f ./mySplit.bash ]] && source ./mySplit.bash; } || source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/mySplit.bash)

findDir=/usr


[[ -n "$1" ]] && [[ -d "$1" ]] && findDir="$1"
: ${findDir:='/usr'} ${ramdiskTransferFlag:=true}

findDir="$(realpath "${findDir}")"
findDir="${findDir%/}"


if ${ramdiskTransferFlag}; then

    grep -qF 'tmpfs /mnt/ramdisk' </proc/mounts || {
        printf '\nMOUNTING RAMDISK AT /mnt/ramdisk\n' >&2
        mkdir -p /mnt/ramdisk
        sudo mount -t tmpfs tmpfs /mnt/ramdisk
        sudo chown -R "$USER": /mnt/ramdisk
    }
    
    printf '\nCOPYING FILES FROM %s TO RAMDISK AT %s\n' "${findDir}" "/mnt/ramdisk/${findDir#/}" >&2
    mkdir -p "/mnt/ramdisk/${findDir}"
    rsync -a "${findDir}"/* "/mnt/ramdisk/${findDir#/}"
    
    findDir="/mnt/ramdisk/${findDir#/}"

fi


nRep=2

declare -a tName tNum tTime tTotal
declare -i tTotal0 ii jj

maxC0=$(printf '%s\n' "${tests[@]}" | wc -L)

[[ -f /mnt/ramdisk/mySplit.test.results ]] && cat /mnt/ramdisk/mySplit.test.results >> /mnt/ramdisk/mySplit.test.results.old && \rm -f /mnt/ramdisk/mySplit.test.results

{
printf '\n\n----------------------------------------------------------------------------RESULTS----------------------------------------------------------------------------\n\n'

[[ $nRep == 1 ]] && printf '%28s\t' '' || printf '%28s\t' "(avg of ${nRep}x runs)"
printf '%'"${maxC0}"'s\t' "${tests[@]}" "TOTAL FOR ALL TESTS" "PRINTF (PING->FIND)"
printf '\n'

ii=0
jj=0

for a1 in 1 2 3; do
    for a2 in 0 1 2; do
    	    
    	    printf '%28s\t' "mySplit -- a1=${a1} a2=${a2}"

    	    tTotal0=0

    	    ((jj++))

    	    for kk in "${!tests[@]}"; do

            nfun=${tests[$kk]}
    
            ((ii++))

            tName[$ii]="mySplit -- a1=${a1} a2=${a2} -- ( $nfun )"

            T0=${EPOCHREALTIME}

            for (( nn=0 ; nn<nRep ; nn++ )); do

                tNum[$ii]+="$({ sleep 0.2s; find "${findDir}" -type f; } | ALG1=${a1} ALG2=${a2} mySplit ${nfun} | wc -l)"$'\n'

            done

            tTime[$ii]="$(myTimeDiff "${T0}")"
            unset T0
            tTotal0+=${tTime[$ii]//./}

            printf '%'"${maxC0}"'s\t' "${tTime[$ii]}"

            numU="$(grep -E '^[0-9]+$' <<<"${tNum[$ii]}" | sort -u | wc -l)"
            (( $numU > 1 )) && printf '\n\nWARNING: TEST "%s" had %s unique file count numbers\n\n' "${tName[$ii]}" "${numU}" >&2

           # sleep 1

        done
        tTotal[$jj]="${tTotal0:0:$(( ${#tTotal0} - 6 ))}.${tTotal0:-6}"
        printf '%19s\t' "${tTotal[$jj]}"

        ((ii++))
        T0=${EPOCHREALTIME}
        for (( nn=0 ; nn<nRep ; nn++ )); do
            tNum[$ii]+="$({ ping -c 50 -i 0.1 1.1.1.1; find "${findDir}" -type f; } | mySplit printf '%s\n' | wc -l)"
        done
        tTime[$ii]="$(myTimeDiff "${T0}")"
        printf '%19s\n' "${tTime[$ii]}"
        numU="$(grep -E '^[0-9]+$' <<<"${tNum[$ii]}" | sort -u | wc -l)"
        (( $numU > 1 )) && printf '\n\nWARNING: TEST "%s" had %s unique file count numbers\n\n' "${tName[$ii]}" "${numU}" >&2


    done
done 

} | tee -a /mnt/ramdisk/mySplit.test.results

cat /mnt/ramdisk/mySplit.test.results
