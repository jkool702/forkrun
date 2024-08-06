#!/usr/bin/env bash

############################################## BEGIN CODE ##############################################

SECONDS=0
shopt -s extglob

renice --priority -20 --pid $$

[[ "$USER" == 'root' ]] && {
	for nn in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo 'performance' >"${nn}"; done
}

declare -F forkrun &>/dev/null || { 
    [[ -f ./forkrun.bash ]] || wget  https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash
    . ./forkrun.bash
}
export -f forkrun

findDirDefault='/usr'

findDir='/mnt/ramdisk/usr'
ramdiskTransferFlag=false

[[ -n "$1" ]] && [[ -d "$1" ]] && findDir="$1"
: ${findDir:="${findDirDefault}"} ${ramdiskTransferFlag:=true}

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
    hfdir0='/mnt/ramdisk/hyperfine'

else

  hfdir0="${findDir%/*}/hyperfine"

fi
"${testParallelFlag:=true}"
testParallelFlag=false
declare -a C0 C1

C0[0]=''
C1[0]=' <"'"${hfdir0}"'"/file_lists/f${kk}'

C0[1]='cat "'"${hfdir0}"'"/file_lists/f${kk} | '
C1[1]=''

C0[2]=''
C1[2]=' <"'"${hfdir0}"'"/file_lists/f${kk} | wc -l'

C0[3]='cat "'"${hfdir0}"'"/file_lists/f${kk} | '
C1[3]=' | wc -l'

C0[4]=''
C1[4]=' <"'"${hfdir0}"'"/file_lists/f${kk} | >/dev/null'

C0[5]='cat "'"${hfdir0}"'"/file_lists/f${kk} | '
C1[5]=' >/dev/null'

mkdir -p "${hfdir0}"/file_lists

nArgs=(1024 4096 16384 65536 262144 1048576)

for kk in {1..6}; do
	find "${findDir}" -type f | head -n ${nArgs[$(($kk-1))]} >"${hfdir0}"/file_lists/f${kk}
done

shopt -s extglob

export -nf forkrun
export -f forkrun

for jj in ${!C0[@]}; do
        
    hfdir="${hfdir0}/C${jj}"

    mkdir -p "${hfdir}"/results

    for kk in {1..6}; do 
        printf '\n-------------------------------- %s values --------------------------------\n\n' $(wc -l <"${hfdir0}"/file_lists/f${kk}); 

        for c in  sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3"; do 
            printf '\n---------------- %s ----------------\n\n' "$c"; 

            if ${testParallelFlag}; then
               hyperfine -w 1 -i --shell=bash --parameter-list cmd 'forkrun -j - --','forkrun --','xargs -P '"$(nproc)"' -d $'"'"'\n'"'"' --','parallel -m --' --export-json ""${hfdir}"/results/forkrun.${c// /_}.f${kk}.hyperfine.results" --style=full --setup 'shopt -s extglob && renice --priority -20 --pid $$' --prepare 'shopt -s extglob && renice --priority -20 --pid $$' '. /mnt/ramdisk/forkrun/forkrun.bash && '"${C0[$jj]//'${kk}'/${kk}}"' {cmd} '"${c}"' '"${C1[$jj]//'${kk}'/${kk}}"
            else
               hyperfine -w 1 -i --shell=bash --parameter-list cmd 'forkrun -j - --','forkrun --','xargs -P '"$(nproc)"' -d $'"'"'\n'"'"' --' --export-json ""${hfdir}"/results/forkrun.${c// /_}.f${kk}.hyperfine.results" --style=full --setup 'shopt -s extglob && renice --priority -20 --pid $$' --prepare 'shopt -s extglob && renice --priority -20 --pid $$' '. /mnt/ramdisk/forkrun/forkrun.bash && '"${C0[$jj]//'${kk}'/${kk}}"' {cmd} '"${c}"' '"${C1[$jj]//'${kk}'/${kk}}"
            fi

        done
    done | tee -a "${hfdir}"/results/forkrun.stdout.results

    # generare quick table of results (raw times)

    for t in '"min"' '"mean"' '"max"'; do
        printf '\n-----------------------------------------------------\n-------------------- %s TIMES --------------------\n-----------------------------------------------------\n\n' "$t"
        printf '%0.11s    \t' '#' sha1sum sha1sum sha256sum sha256sum sha512sum sha512sum sha224sum sha224sum sha384sum sha384sum md5sum md5sum  "sum -s" "sum -s" "sum -r" "sum -r" cksum cksum b2sum b2sum "cksum -a sm3" "cksum -a sm3" 
        printf '\n(stdin)\t'; 
        for kk in {1..11}; do printf '%0.12s    \t' '(forkrun)' '(xargs)' "$(${testParallelFlag} && echo '(parallel)')"; done; 
            printf '\n\n'; 
            for kk in {1..6}; do
                printf '%s\t' $(wc -l <"${hfdir0}"/file_lists/f$kk)
                for c in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3"; do
                printf '%0.12s\t' $(grep -F "$t" < "${hfdir}"/results/forkrun."${c// /_}".f${kk}.hyperfine.results | sed -E s/'^.*\:'//)
            done
            printf '\n'
        done
    done

    # generate "real" table of results (the good one that looks all pretty.
    printf0() {
        local -a val pad
        local nn nn1 padStr 
        local -i kk padMax padLast

        padMax=0
        padLast=0

        for nn in "$@"; do
            nn1="${nn//[, ]/}"
            
            if [[ "$nn1" == *\:* ]]; then
                val+=("${nn##*\:}")
                pad+=("$(( ${nn%%\:*} - ${#val[-1]} ))")
                padLast=${nn%%\:*}
            else
                val+=(${nn})
                pad+=("$(( ${padLast} - ${#val[-1]} ))")
            fi

            (( ${pad[-1]} < 0 )) && pad[-1]=0
            (( ${pad[-1]} > ${padMax} )) && padMax=${pad[-1]}
        done

        padStr="$(source /proc/self/fd/0 <<<"printf '%.0s ' {1..${padMax}}")"

        for kk in ${!val[@]}; do
            val[$kk]+="${padStr:0:${pad[$kk]}}"
        done

        printf '%s\t' "${val[@]}"

    }

    myMin() {
	if (( ${1%.*} < ${2%.*} )); then 
		echo "$1"
	elif (( ${1%.*} > ${2%.*} )); then 
		echo "$2"
	elif (( ${1#*.} < ${2#*.} )); then 
		echo "$1"
	elif (( ${1#*.} > ${2#*.} )); then 
		echo "$2"
	else
		echo "$1"
	fi
    }

    {
    printf '\n\n||-----------------------------------------------------------------------------------------------------------------------------------------------------------||\n||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||\n||-----------------------------------------------------------------------------------------------------------------------------------------------------------||\n'  

    for kk in {1..6}; do

        printf '\n\n\n%.157s|| \n\n' "$(printf '||----------------------------------------------------------------- NUM_CHECKSUMS=%s -------------------------------------------------------------------------' $(wc -l <"${hfdir0}/file_lists/f${kk}"))"
        printf0 8:'(algorithm)' 
        if ${testParallelFlag}; then
		printf0 12:'(forkrun-nq)' 12:'(forkrun)' 12:'(xargs)' 12:'(parallel)' 44:'(relative performance vs xargs)' 44:'(relative performance vs parallel)'
        else
            printf0 12:'(forkrun)' 12:'(xargs)' 44:'(relative performance vs xargs)'
        fi
        printf '\n%s\t' '------------'
        if ${testParallelFlag}; then
            printf0 12:'------------' '------------' '------------'  '------------' 44:'--------------------------------------------' 44:'-----------------------------------------------'
        else
            printf0 12:'------------' '------------' 44:'--------------------------------------------'
        fi
        printf '\n'
        declare -a A0 
        T0=0.0
        T1=0.0
        T2=0.0
        ${testParallelFlag} && T3=0.0
        for c in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3" OVERALL; do
            if [[ "${c}" == 'OVERALL' ]]; then
                if ${testParallelFlag}; then
		    A0=(${T0} ${T1} ${T2} ${T3})
                else
                    A0=(${T0} ${T1} ${T2})
                fi
                printf '\n'
            else
                mapfile -t A0 < <(grep -F "mean" < "${hfdir}"/results/forkrun."${c// /_}".f${kk}.hyperfine.results | sed -E s/'^.*\:'//)
                A0=("${A0[@]//[ ,]/}")

                T0="$(bc <<<"${T0} + ${A0[0]}")"
                T1="$(bc <<<"${T1} + ${A0[1]}")"
                T2="$(bc <<<"${T2} + ${A0[2]}")"
                ${testParallelFlag} && T3="$(bc <<<"${T3} + ${A0[3]}")"  
            fi
                
            printf0 12:"$c" $(printf '%.12s ' "${A0[@]}")
	    A0=($(myMin "${A0[@]:0:2}") "${A0[@]:2}")

           
            if [[ $(bc <<< "${A0[0]} / ${A0[1]}") == '0' ]]; then
                ratio="$(bc <<<"scale=10; ${A0[1]} / ${A0[0]}")"
                printf0 44:"$(printf 'forkrun is %.5s%% faster than xargs (%.6sx)'  "$(bc <<< "( $ratio * 100 ) - 100")" "${ratio}")"
            else
                ratio="$(bc <<<"scale=10; ${A0[0]} / ${A0[1]}")"
                printf0 44:"$(printf 'xargs is %.5s%% faster than forkrun (%.6sx)'  "$(bc <<< "( $ratio * 100 ) - 100")" "${ratio}")"
            fi
            if ${testParallelFlag}; then
                if [[ $(bc <<< "${A0[0]} / ${A0[2]}") == '0' ]]; then
                    ratio1="$(bc <<<"scale=10; ${A0[2]} / ${A0[0]}")"
                    printf0 44:"$(printf 'forkrun is %.5s%% faster than parallel (%.6sx)' "$(bc <<< "( $ratio1 * 100 ) - 100")" "${ratio1}")"
                else
                    ratio1="$(bc <<<"scale=10; ${A0[0]} / ${A0[2]}")"
                    printf0 44:"$(printf 'parallel is %.5s%% faster than forkrun (%.6sx)' "$(bc <<< "( $ratio1 * 100 ) - 100")" "${ratio1}")"
                fi
            fi
            printf '\n'
        done
        printf '\n'
    done
    } | tee "${hfdir}"/results/results-table

done
