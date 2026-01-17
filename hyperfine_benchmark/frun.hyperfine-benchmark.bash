#!/usr/bin/env bash

############################################## BEGIN CODE ##############################################

SECONDS=0
shopt -s extglob

renice --priority -20 --pid $$

[[ "$USER" == 'root' ]] && {
	for nn in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo 'performance' >"${nn}"; done
}

declare -F forkrun &>/dev/null || { 
    [[ -f ./forkrun.bash ]] || wget https://raw.githubusercontent.com/jkool702/forkrun/refs/heads/forkrun_testing_async-io_3/forkrun.bash
    . ./forkrun.bash
}
#declare -F frun &>/dev/null || { 
#    [[ -f ./frun.bash ]] || wget https://raw.githubusercontent.com/jkool702/forkrun/refs/heads/forkrun_testing_async-io_3/ring_loadables/frun.bash
    . ./frun.bash
	export -f frun
	export FORKRUN_MEMFD_LOADABLES="${FORKRUN_MEMFD_LOADABLES}"
        export FORKRUN_RING_ENABLED=true	
#}
ring_list 'ring_listA'
printf -v ring_enable '%s ' "${ring_listA[@]}" 'ring_list'
export ring_enable="${ring_enable% }"
#export -f frun

: <<EOC
source /proc/self/fd/0 <<EOI
_forkrun_export() {
shopt -s extglob
source /proc/self/fd/0 <<'EeEOoOFfF'
$(declare -f forkrun)
$(declare -f _forkrun_complete)
$(declare -f _forkrun_displayHelp)
$(declare -f _forkrun_lseek_setup)
complete -o bashdefault -o nosort -F _forkrun_complete forkrun
_forkrun_lseek_setup
export -f forkrun
export -f _forkrun_complete
export -f _forkrun_displayHelp
export -f _forkrun_lseek_setup
EeEOoOFfF
}
EOI

export -f _forkrun_export
EOC

findDirDefault='/usr'

[[ -n "$1" ]] && [[ -d "$1" ]] && findDir="$1"

[[ -d /mnt/ramdisk/usr ]] && [[ -z "${findDir}" ]] && {
    findDir='/mnt/ramdisk/usr'
    ramdiskTransferFlag=false
}

: "${findDir:="${findDirDefault}"}" "${ramdiskTransferFlag:=true}" "${nullFlag:=false}"
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
    rsync -a --max-size=$((1<<20)) "${findDir}"/* "/mnt/ramdisk/${findDir#/}"
    
    findDir="/mnt/ramdisk/${findDir#/}"
    hfdir0='/mnt/ramdisk/hyperfine'

else

  hfdir0="${findDir%/*}/hyperfine"

fi
"${testForkrunFlag:=true}"
testForkrunFlag=true

declare -a C0 C1

C0[0]=''
C1[0]=' <"'"${hfdir0}"'"/file_lists/f${kk}'

#C0[1]='cat "'"${hfdir0}"'"/file_lists/@f${kk} | '
#C1[1]=''

#C0[2]=''
#C1[2]=' <"'"${hfdir0}"'"/file_lists/@f${kk} | wc -l'

#C0[3]='cat "'"${hfdir0}"'"/file_lists/@f${kk} | '
#C1[3]=' | wc -l'

#C0[4]=''
#C1[4]=' <"'"${hfdir0}"'"/file_lists/@f${kk} >/dev/null'

#C0[5]='cat "'"${hfdir0}"'"/file_lists/@f${kk} | '
#C1[5]=' >/dev/null'

mkdir -p "${hfdir0}"/file_lists

find "${findDir}" -type f $(${nullFlag} && printf '%s' '-print0') >"${hfdir0}"/file_lists/f0

nArgsMax="$(tr '\0' '\n' <"${hfdir0}"/file_lists/f0 | wc -l)"
nArgs=('' 4096)
until (( ( 4 * nArgs[-1] ) >= nArgsMax )); do
	nArgs+=($((4 * nArgs[-1])))
done
nArgs+=(${nArgsMax})

cksumAlgsA=(sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3" xxhsum "xxhsum -H3")

testAlgsA=(':' 'echo' 'printf '"'"'%s\n'"'")

fA=("${cksumAlgsA[@]//*/f}")
fA+=(s s s n n n)

cksumAlgsA+=("${testAlgsA[@]}" "${testAlgsA[@]}")

seq 100000000 >"${hfdir0}"/file_lists/s0
yes $'\n' | head -n 100000000 >"${hfdir0}"/file_lists/n0
nA=()

#if ${nullFlag}; then
#    nArgsMax="$(tr $'\x00' $'\n' <"${hfdir0}"/file_lists/f0 | wc -l)"
#else
#    nArgsMax="$(wc -l <"${hfdir0}"/file_lists/f0)"
#fi
for (( kk=1; kk<${#nArgs[@]}; kk++ )); do

	shuf $(${nullFlag} && printf '%s' '-z') -n ${nArgs[$kk]} >"${hfdir0}"/file_lists/f${kk} <"${hfdir0}"/file_lists/f0

	(( K = 8 + kk - ${#nArgs[@]} ))
	(( K = (K >= 0) ? 10 ** K : 1 ))
	nA+=($K)

	head -n $K <"${hfdir0}"/file_lists/s0 >"${hfdir0}"/file_lists/s${kk}
	head -n $K <"${hfdir0}"/file_lists/n0 >"${hfdir0}"/file_lists/n${kk}

#    (( nArgs[$kk] >= nArgsMax )) && {
#        nArgs=("${nArgs[@]:0:$((kk+1))}")
#        break
#    }
done
nA+=($(( ${nA[-1]} * 10 )))

for jj in "${!C0[@]}"; do
        
    hfdir="${hfdir0}/C${jj}"

    mkdir -p "${hfdir}"/results

    for (( kk=1; kk<${#nArgs[@]}; kk++ )); do
        printf '\n-------------------------------- STARTING TESTING FOR %s CHECKSUMS / %s VALUES --------------------------------\n\n' "${nArgs[$kk]}" "${nA[$kk]}"; 

        for ckk in "${!cksumAlgsA[@]}"; do
		c="${cksumAlgsA[$ckk]}"
		fC=${fA[$ckk]}
		case "${fA[$ckk]}" in
		f) printf '\n---------------- %s (%s) (cksum) ----------------\n\n' "$c" "${nArgs[$kk]}" ;;
		s) printf '\n---------------- %s (%s) (seq) ------------------\n\n' "$c" "${nA[$kk]}" ;;
		n) printf '\n---------------- %s (%s) (newline) --------------\n\n' "$c" "${nA[$kk]}" ;;
		esac
		

#            if ${testForkrunFlag}; then
		       hyperfine -w 1 -i --shell=bash --parameter-list cmd 'frun -o '"$(${nullFlag} && printf '%s' '-d '"''")"' --','frun '"$(${nullFlag} && printf '%s' '-d '"''")"' --','xargs -P '"$(nproc)"' '"$(${nullFlag} && printf '%s' '-0 '|| printf '%s' '-d $'"'"'\n'"'")"' --','/usr/bin/bash -O extglob -c . /mnt/ramdisk/forkrun/forkrun.bash && forkrun '"$(${nullFlag} && printf '%s' '-z ')" --export-json ""${hfdir}"/results/frun.${c// /_}.${fC}${kk}.hyperfine.results" --style=full --setup 'shopt -s extglob && renice --priority -20 --pid $$' --prepare 'shopt -s extglob && renice --priority -20 --pid $$' 'enable -f /mnt/ramdisk/forkrun/ring_loadables/forkrun_ring.native.so ${ring_enable} &&  '"${C0[$jj]//'f${kk}'/${fC}${kk}}"' {cmd} '"${c}"' '"${C1[$jj]//'f${kk}'/${fC}${kk}}"
#            else
#               hyperfine -w 1 -i --shell=bash --parameter-list cmd \
#               'frun -o '"$(${nullFlag} && printf '%s' '-d '"''")"' --',\
#               'frun '"$(${nullFlag} && printf '%s' '-d '"''")"' --',\
#               'xargs -P '"$(nproc)"' '"$(${nullFlag} && printf '%s' '-0 '|| printf '%s' '-d $'"'"'\n'"'")"' --'\
#               --export-json ""${hfdir}"/results/frun.${c// /_}.${fA[$ckk]}${kk}.hyperfine.results" --style=full \
#               --setup 'shopt -s extglob && renice --priority -20 --pid $$' \
#               --prepare 'shopt -s extglob && renice --priority -20 --pid $$' \
#               'enable -f /mnt/ramdisk/forkrun/ring_loadables/forkrun_ring.native.so ${ring_list} && '"${C0[$jj]//'f${kk}'/${fA[$ckk]}${kk}}"' {cmd} '"${c}"' '"${C1[$jj]//'f${kk}'/${fA[$ckk]}${kk}}"
#            fi

        done
    done  | tee -a "${hfdir}"/results/frun.stdout.results

    # generare quick table of results (raw times)

    for t in '"min"' '"mean"' '"max"'; do
        printf '\n-----------------------------------------------------\n-------------------- %s TIMES --------------------\n-----------------------------------------------------\n\n' "$t"
	printf "$(printf '%0.11s    \t%%0.11s    \t' '#' "${cksumAlgsA[@]}" )" "${cksumAlgsA[@]}"
        printf '\n(stdin)\t'; 
        for kk in {1..${#cksumAlgsA[@]}}; do 
	    printf '%0.12s    \t' '(frun)' '(xargs)' "$(${testForkrunFlag} && echo '(forkrun)')"; 
        done; 
        printf '\n\n'; 
        for kk in "${!nArgs[@]}"; do [[ "$kk" == 0 ]] && continue
            printf '%s\t' "${nArgs[$kk]}"
            for ckk in "${!cksumAlgsA[@]}"; do
		        c="${cksumAlgsA[$ckk]}"
		        printf '%0.12s\t' $(grep -F "$t" < "${hfdir}"/results/frun."${c// /_}".${fA[$ckk]}${kk}.hyperfine.results | sed -E s/'^.*\:'//)
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

        for kk in "${!val[@]}"; do
            val[$kk]+="${padStr:0:${pad[$kk]}}"
        done

        printf '%s\t' "${val[@]}"

    }
    
    shopt -s extglob
    myMin() {
        shopt -s extglob
	if (( $([[ "$1" == .* ]] && printf '0')${1%.*} < $([[ "$2" == .* ]] && printf '0')${2%.*} )); then 
		echo "$1"
    elif (( $([[ "$1" == .* ]] && printf '0')${1%.*} > $([[ "$2" == .* ]] && printf '0')${2%.*} )); then 
		echo "$2"
	elif (( ${1##*.*(0)} < ${2##*.*(0)} )); then 
		echo "$1"
	elif (( ${1##*.*(0)} > ${2##*.*(0)} )); then 
		echo "$2"
	else
		echo "$1"
	fi
    }

    {
    printf '\n\n||-----------------------------------------------------------------------------------------------------------------------------------------------------------||\n||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||\n||-----------------------------------------------------------------------------------------------------------------------------------------------------------||\n'  

    for (( kk=1; kk<${#nArgs[@]}; kk++ )); do

        printf '\n\n\n%.157s|| \n\n' "$(printf '||----------------------------------------------------------------- NUM_CHECKSUMS=%s -------------------------------------------------------------------------' ${nArgs[$kk]})"
        printf0 8:'(algorithm)' 
        if ${testForkrunFlag}; then
		printf0 12:'(frun -o)' 12:'(frun)' 12:'(xargs)' 12:'(forkrun)' 44:'(relative performance vs xargs)' 44:'(relative performance vs forkrun)'
        else
            printf0 12:'(frun -o)' 12:'(frun)' 12:'(xargs)' 44:'(relative performance vs xargs)'
        fi
        printf '\n%s\t' '------------'
        if ${testForkrunFlag}; then
            printf0 12:'------------' '------------' '------------'  '------------' 44:'--------------------------------------------' 44:'-----------------------------------------------'
        else
            printf0 12:'------------' '------------' '------------' 44:'--------------------------------------------'
        fi
        printf '\n'
        declare -a A0 
        T0=0.0
        T1=0.0
        T2=0.0
        ${testForkrunFlag} && T3=0.0
        for ckk in "${!cksumAlgsA[@]}"; do
		    c=-"${cksumAlgsA[$ckk]}"
            if [[ "${c}" == 'OVERALL' ]]; then
                if ${testForkrunFlag}; then
		            A0=(${T0} ${T1} ${T2} ${T3})
                else
                    A0=(${T0} ${T1} ${T2})
                fi
                printf '\n'
            else
                mapfile -t A0 < <(grep -F "mean" < "${hfdir}"/results/frun."${c// /_}".${fA[$ckk]}${kk}.hyperfine.results | sed -E s/'^.*\:'//)
                A0=("${A0[@]//[ ,]/}")

                T0="$(bc <<<"${T0} + ${A0[0]}")"
                T1="$(bc <<<"${T1} + ${A0[1]}")"
                T2="$(bc <<<"${T2} + ${A0[2]}")"
                ${testForkrunFlag} && T3="$(bc <<<"${T3} + ${A0[3]}")"  
            fi
                
            printf0 12:"$c" $(printf '%.12s ' "${A0[@]}")
	    A0=($(myMin "${A0[@]:0:2}") "${A0[@]:2}")

           
            if [[ $(bc <<< "${A0[0]} / ${A0[1]}") == '0' ]]; then
                ratio="$(bc <<<"scale=10; ${A0[1]} / ${A0[0]}")"
                printf0 44:"$(printf 'frun is %.5s%% faster than xargs (%.6sx)'  "$(bc <<< "( $ratio * 100 ) - 100")" "${ratio}")"
            else
                ratio="$(bc <<<"scale=10; ${A0[0]} / ${A0[1]}")"
                printf0 44:"$(printf 'xargs is %.5s%% faster than frun (%.6sx)'  "$(bc <<< "( $ratio * 100 ) - 100")" "${ratio}")"
            fi
            if ${testForkrunFlag}; then
                if [[ $(bc <<< "${A0[0]} / ${A0[2]}") == '0' ]]; then
                    ratio1="$(bc <<<"scale=10; ${A0[2]} / ${A0[0]}")"
                    printf0 44:"$(printf 'frun is %.5s%% faster than forkrun (%.6sx)' "$(bc <<< "( $ratio1 * 100 ) - 100")" "${ratio1}")"
                else
                    ratio1="$(bc <<<"scale=10; ${A0[0]} / ${A0[2]}")"
                    printf0 44:"$(printf 'forkrun is %.5s%% faster than frun (%.6sx)' "$(bc <<< "( $ratio1 * 100 ) - 100")" "${ratio1}")"
                fi
            fi
            printf '\n'
        done
        printf '\n'
    done
    } | tee "${hfdir}"/results/results-table

done
