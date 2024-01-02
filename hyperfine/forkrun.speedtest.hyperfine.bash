
############################################## BEGIN CODE ##############################################

SECONDS=0
shopt -s extglob

renice --priority -20 --pid $$

declare -F forkrun 1>/dev/null 2>&1 || { 
    [[ -f ./forkrun.bash ]] || wget  https://raw.githubusercontent.com/jkool702/forkrun/forkrun-testing/forkrun.bash
    . ./forkrun.bash
}

findDirDefault='/usr'

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
    \rm  -rf ./usr/lib64/dri
    
    findDir="/mnt/ramdisk/${findDir#/}"
    hfdir='/mnt/ramdisk/hyperfine'

else

  hfdir="${PWD}/hyperfine"

fi
testParallelFlag=false
"${testParallelFlag:=true}"

mkdir -p "${hfdir}"/{results,file_lists}

for kk in {1..6}; do
    find "${findDir}" -type f | head -n $(( 10 ** $kk )) >"${hfdir}"/file_lists/f${kk}
done

for kk in {1..6}; do 
    printf '\n-------------------------------- %s values --------------------------------\n\n' $(wc -l <"${hfdir}"/file_lists/f${kk}); 

    for c in  sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3"; do 
        printf '\n---------------- %s ----------------\n\n' "$c"; 

        if ${testParallelFlag}; then
           hyperfine -w 1 -i --shell /usr/bin/bash --parameter-list cmd 'source '"${PWD}"'/forkrun.bash && forkrun --','xargs -P '"$(nproc)"' -d $'"'"'\n'"'"' --','parallel -m --' --export-json ""${hfdir}"/results/forkrun.${c// /_}.f${kk}.hyperfine.results" --style=full --setup 'shopt -s extglob' --prepare 'renice --priority -20 --pid $$' '{cmd} '"${c}"' <'"${hfdir}"'/file_lists/f'"${kk}" 
        else
            hyperfine -w 1 -i --shell /usr/bin/bash --parameter-list cmd 'source '"${PWD}"'/forkrun.bash && forkrun --','xargs -P '"$(nproc)"' -d $'"'"'\n'"'"' --' --export-json ""${hfdir}"/results/forkrun.${c// /_}.f${kk}.hyperfine.results" --style=full --setup 'shopt -s extglob' --prepare 'renice --priority -20 --pid $$' '{cmd} '"${c}"' <'"${hfdir}"'/file_lists/f'"${kk}" 
        fi

    done
done | tee -a "${hfdir}"/results/forkrun.stdout.results

for t in '"min"' '"mean"' '"max"'; do
    printf '\n-----------------------------------------------------\n-------------------- %s TIMES --------------------\n-----------------------------------------------------\n\n' "$t"
    printf '%0.11s    \t' '#' sha1sum sha1sum sha256sum sha256sum sha512sum sha512sum sha224sum sha224sum sha384sum sha384sum md5sum md5sum  "sum -s" "sum -s" "sum -r" "sum -r" cksum cksum b2sum b2sum "cksum -a sm3" "cksum -a sm3" 
    printf '\n(stdin)\t'; 
    for kk in {1..11}; do printf '%0.12s    \t' '(forkrun)' '(xargs)'; done; 
        printf '\n\n'; 
        for kk in {1..6}; do
            printf '%s\t' $(wc -l <"${hfdir}"/file_lists/f$kk)
            for c in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3"; do
            printf '%0.12s\t' $(grep -F "$t" < "${hfdir}"/results/forkrun."${c// /_}".f${kk}.hyperfine.results | sed -E s/'^.*\:'//)
        done
        printf '\n'
    done
done

shopt -s extglob

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


printf0 32:'((RUN_TIME_IN_SECONDS))'  $(${testParallelFlag} && printf '86' || printf '70'):$(for nn in {1..6}; do printf 'NUM_CHECKSUMS=%s ' $(wc -l <"${hfdir}/file_lists/f${nn}"); done)
printf '\n'
printf0 8:' ' 
for kk in {1..6}; do
    if ${testParallelFlag}; then
        printf0 150:'----------------------------------------------------------------------------------------------------------------------------------------------------------------'
    else
        printf0 70:'----------------------------------------------------------------'
    fi
done
printf '\n'
printf0 8:'(algorithm)' 
for kk in {1..6}; do
    if ${testParallelFlag}; then
        printf0 12:'  (forkrun)' 12:'   (xargs)' 12:'  (parallel)' 50:'(relative performance vs xargs)' 50:'(relative performance vs parallel)'
    else
        printf0 12:'  (forkrun)' 12:'   (xargs)' 38:'    (relative performance)'
    fi
done
printf '\n%s\t' '------------'
for kk in {1..6}; do
    if ${testParallelFlag}; then
        printf0 12:'------------' '------------' '------------' 50:'--------------------------------' 50:'--------------------------------'
    else
        printf0 12:'------------' '------------' 38:'--------------------------------'
    fi
done
printf '\n'
declare +i -a A
for c in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3"; do
    printf0 12:"${c}"
    for kk in {1..6}; do
        mapfile -t A < <(grep -F "$t" < "${hfdir}"/results/forkrun."${c// /_}".f${kk}.hyperfine.results | sed -E s/'^.*\:'//)
        A=("${A[@]%%*([ ,])}")
        A=("${A[@]##*( )}")
        printf0 12:$(printf '%.12s ' "${A[@]}")
        mapfile -t -d $'\t' A < <(printf0 12:$(printf '%.12s ' "${A[@]}"))
        A=("${A[@]//\ /0}")

        A_min=${#A[0]}
        (( ${#A[1]} < $A_min )) && A_min=${#A[1]}
        ${testParallelFlag} && (( ${#A[2]} < $A_min )) && A_min=${#A[2]}

        if ${testParallelFlag}; then
            A=("${A[0]:0:${A_min}}" "${A[1]:0:${A_min}}" "${A[2]:0:${A_min}}")
        else
            A=("${A[0]:0:${A_min}}" "${A[1]:0:${A_min}}")
        fi

        A=("${A[@]##*([0\.\(\:\)\,])}")
        A=("${A[@]//./}")
        if (( ${A[0]} < ${A[1]} )); then
            ratio="$(( ( ( 10000 * ${A[1]//./} ) / ${A[0]//./} ) ))"
            printf0 $(${testParallelFlag} && printf '50' || printf '38'):"$(printf 'forkrun is %s%% faster '"$(${testParallelFlag} && printf 'than xargs ')"'(%s.%sx)' "$(( ( $ratio / 100 ) - 100 ))" "${ratio:0:$(( ${#ratio} - 4 ))}" "${ratio:$(( ${#ratio} - 4 ))}")"
        else
            ratio="$(( ( ( 10000 * ${A[0]//./} ) / ${A[1]//./} ) ))"
            printf0 $(${testParallelFlag} && printf '50' || printf '38'):"$(printf 'xargs is %s%% faster '"$(${testParallelFlag} && printf 'than forkrun ')"'(%s.%sx)' "$(( ( $ratio / 100 ) - 100 ))" "${ratio:0:$(( ${#ratio} - 4 ))}" "${ratio:$(( ${#ratio} - 4 ))}")"
        fi
        if ${testParallelFlag}; then
            ratio1="$(( ( ( 10000 * ${A[2]//./} ) / ${A[0]//./} ) ))"
            printf0 50:"$(printf 'forkrun is %s%% faster than parallel (%s.%sx)' "$(( ( $ratio1 / 100 ) - 100 ))" "${ratio1:0:$(( ${#ratio1} - 4 ))}" "${ratio1:$(( ${#ratio1} - 4 ))}")"
        fi
    done
    printf '\n'
done


# RESULTS
:<<'EOF'
((RUN_TIME_IN_SECONDS))                 NUM_CHECKSUMS=10                                                        NUM_CHECKSUMS=100                                                       NUM_CHECKSUMS=1000                                                      NUM_CHECKSUMS=10000                                                     NUM_CHECKSUMS=100000                                                    NUM_CHECKSUMS=523216                                                  
                ----------------------------------------------------------------        ----------------------------------------------------------------        ----------------------------------------------------------------        ----------------------------------------------------------------        ----------------------------------------------------------------        ----------------------------------------------------------------      
(algorithm)       (forkrun)        (xargs)          (relative performance)                (forkrun)        (xargs)          (relative performance)                (forkrun)        (xargs)          (relative performance)                (forkrun)        (xargs)          (relative performance)                (forkrun)        (xargs)          (relative performance)                (forkrun)        (xargs)          (relative performance)            
------------    ------------    ------------    --------------------------------        ------------    ------------    --------------------------------        ------------    ------------    --------------------------------        ------------    ------------    --------------------------------        ------------    ------------    --------------------------------        ------------    ------------    --------------------------------      
sha1sum         0.0228975587    0.0021664207    xargs is 956% faster (10.5693x)         0.0623609216    0.0958004456    forkrun is 53% faster (1.5362x)         0.3229400739    0.8600093009    forkrun is 166% faster (2.6630x)        0.7908353235    1.8609302515    forkrun is 135% faster (2.3531x)        1.2247026807    1.9775493287    forkrun is 61% faster (1.6147x)         2.1901131371    2.3933036801    forkrun is 9% faster (1.0927x)        
sha256sum       0.0226907878    0.0020600128    xargs is 1001% faster (11.0148x)        0.1042551178    0.1925103098    forkrun is 84% faster (1.8465x)         0.5630335545    1.8077166795    forkrun is 221% faster (3.2106x)        1.5623738702    3.9406321642    forkrun is 152% faster (2.5222x)        2.3829185010    4.1801513090    forkrun is 75% faster (1.7542x)         4.0786752150    4.8757760220    forkrun is 19% faster (1.1954x)       
sha512sum       0.0227543133    0.0021115343    xargs is 977% faster (10.7761x)         0.0791253652    0.1336600002    forkrun is 68% faster (1.6892x)         0.4429939460    1.2334394340    forkrun is 178% faster (2.7843x)        1.0529271970    2.7381661801    forkrun is 160% faster (2.6005x)        1.7245715481    2.8161607231    forkrun is 63% faster (1.6329x)         3.0355304487    3.3690949437    forkrun is 10% faster (1.1098x)       
sha224sum       0.0227405750    0.0021249840    xargs is 970% faster (10.7015x)         0.1046000948    0.1893430608    forkrun is 81% faster (1.8101x)         0.6385075643    1.7568654463    forkrun is 175% faster (2.7515x)        1.5655999155    3.9137689035    forkrun is 149% faster (2.4998x)        2.328941683     4.1333943       forkrun is 77% faster (1.7747x)         4.0183398374    4.8581199094    forkrun is 20% faster (1.2089x)       
sha384sum       0.0231124737    0.0021460107    xargs is 976% faster (10.7699x)         0.0798828991    0.1310201541    forkrun is 64% faster (1.6401x)         0.4026312126    1.2005169636    forkrun is 198% faster (2.9816x)        1.0605891842    2.7222831442    forkrun is 156% faster (2.5667x)        1.6941936284    2.8387357735    forkrun is 67% faster (1.6755x)         3.0735235908    3.4018984438    forkrun is 10% faster (1.1068x)       
md5sum          0.0228479435    0.0020507325    xargs is 1014% faster (11.1413x)        0.0787740830    0.1294128550    forkrun is 64% faster (1.6428x)         0.4187309519    1.1639527849    forkrun is 177% faster (2.7797x)        1.0263507077    2.6236929187    forkrun is 155% faster (2.5563x)        1.4883525722    2.5812156412    forkrun is 73% faster (1.7342x)         2.3331999865    2.7350466645    forkrun is 17% faster (1.1722x)       
sum -s          0.0223908769    0.0016600549    xargs is 1248% faster (13.4880x)        0.0300872079    0.0213490399    xargs is 40% faster (1.4093x)           0.085035415     0.1844419990    forkrun is 116% faster (2.1690x)        0.1982950127    0.4151079387    forkrun is 109% faster (2.0933x)        0.3750679134    0.5520207794    forkrun is 47% faster (1.4717x)         0.8294550860    1.1266189690    forkrun is 35% faster (1.3582x)       
sum -r          0.0221777563    0.0016084583    xargs is 1278% faster (13.7882x)        0.0769152264    0.1320084134    forkrun is 71% faster (1.7162x)         0.4195612192    1.1831475832    forkrun is 181% faster (2.8199x)        1.0316393770    2.5745215610    forkrun is 149% faster (2.4955x)        1.4935082686    2.6938185246    forkrun is 80% faster (1.8036x)         2.2593322410    2.8062692160    forkrun is 24% faster (1.2420x)       
cksum           0.0229761049    0.0020637659    xargs is 1013% faster (11.1330x)        0.0287677803    0.0158464363    xargs is 81% faster (1.8154x)           0.0700222129    0.1343218709    forkrun is 91% faster (1.9182x)         0.149270862     0.3015391450    forkrun is 102% faster (2.0200x)        0.2981644694    0.4521087184    forkrun is 51% faster (1.5163x)         0.7633647118    1.1106532538    forkrun is 45% faster (1.4549x)       
b2sum           0.0225403794    0.0017399104    xargs is 1195% faster (12.9549x)        0.0713991948    0.1151591638    forkrun is 61% faster (1.6128x)         0.3764101116    1.0833418616    forkrun is 187% faster (2.8780x)        0.9660892357    2.3769900597    forkrun is 146% faster (2.4604x)        1.5151152033    2.4653708053    forkrun is 62% faster (1.6271x)         2.6501455329    2.9071726339    forkrun is 9% faster (1.0969x)        
cksum -a sm3    0.0228634608    0.0021010068    xargs is 988% faster (10.8821x)         0.1723447310    0.3438100340    forkrun is 99% faster (1.9948x)         1.0046851802    3.2255455712    forkrun is 221% faster (3.2105x)        2.7967673503    7.0860510003    forkrun is 153% faster (2.5336x)        4.3362087352    7.5085174762    forkrun is 73% faster (1.7315x)         7.2440910516    8.7723690785    forkrun is 21% faster (1.2109x)       
EOF
