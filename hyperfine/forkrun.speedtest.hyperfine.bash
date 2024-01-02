
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


printf '\n\n||-----------------------------------------------------------------||\n||-----------------------RUN_TIME_IN_SECONDS-----------------------||\n||-----------------------------------------------------------------||\n'  

for kk in {1..6}; do

    printf '\n\n\n||--------------------------------------------------------NUM_CHECKSUMS=%s--------------------------------------------------------------------------------|| \n\n' $(wc -l <"${hfdir}/file_lists/f${kk}")
    printf0 8:'(algorithm)' 
    if ${testParallelFlag}; then
        printf0 12:'  (forkrun)' 12:'   (xargs)' 12:'  (parallel)' 50:'(relative performance vs xargs)' 50:'(relative performance vs parallel)'
    else
        printf0 12:'  (forkrun)' 12:'   (xargs)' 38:'    (relative performance)'
    fi
    printf '\n%s\t' '------------'
    if ${testParallelFlag}; then
        printf0 12:'------------' '------------' '------------' 50:'--------------------------------' 50:'--------------------------------'
    else
        printf0 12:'------------' '------------' 38:'--------------------------------'
    fi
    printf '\n'
    declare +i -a A
    for c in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3"; do
        printf0 12:"${c}"
            mapfile -t A < <(grep -F "mean" < "${hfdir}"/results/forkrun."${c// /_}".f${kk}.hyperfine.results | sed -E s/'^.*\:'//)
            A=("${A[@]%%*([ ,])}")
            A=("${A[@]##*( )}")
            printf0 12:$(printf '%.12s ' "${A[@]}")
            mapfile -t -d $'\t' A < <(printf0 12:$(printf '%.12s ' "${A[@]}"))
            A=("${A[@]//\ /0}")

            A1=("${A[@]%%.*}")
            A0=("${A[@]##*.}")

            A_min=${#A0[0]}
            (( ${#A0[1]} < $A_min )) && A_min=${#A0[1]}
            ${testParallelFlag} && (( ${#A0[2]} < $A_min )) && A_min=${#A0[2]}

            if ${testParallelFlag}; then
                A=("${A1[0]}.${A0[0]:0:${A_min}}" "${A1[1]}.${A0[1]:0:${A_min}}" "${A1[2]}.${A0[2]:0:${A_min}}")
            else
                A=("${A[0]:0:${A_min}}" "${A[1]:0:${A_min}}")
            fi

            A=("${A[@]##*([0\.\(\:\)\,])}")
            A=("${A[@]//./}")
            if (( ${A[0]} < ${A[1]} )); then
                ratio="$(( ( ( 10000 * ${A[1]//./} ) / ${A[0]//./} ) ))"
                printf0 $(${testParallelFlag} && printf '44' || printf '38'):"$(printf 'forkrun is %s%% faster '"$(${testParallelFlag} && printf 'than xargs ')"'(%s.%sx)' "$(( ( $ratio / 100 ) - 100 ))" "${ratio:0:$(( ${#ratio} - 4 ))}" "${ratio:$(( ${#ratio} - 4 ))}")"
            else
                ratio="$(( ( ( 10000 * ${A[0]//./} ) / ${A[1]//./} ) ))"
                printf0 $(${testParallelFlag} && printf '44' || printf '38'):"$(printf 'xargs is %s%% faster '"$(${testParallelFlag} && printf 'than forkrun ')"'(%s.%sx)' "$(( ( $ratio / 100 ) - 100 ))" "${ratio:0:$(( ${#ratio} - 4 ))}" "${ratio:$(( ${#ratio} - 4 ))}")"
            fi
            if ${testParallelFlag}; then
                if (( ${A[0]} < ${A[2]} )); then
                    ratio1="$(( ( ( 10000 * ${A[2]//./} ) / ${A[0]//./} ) ))"
                    printf0 44:"$(printf 'forkrun is %s%% faster than parallel (%s.%sx)' "$(( ( $ratio1 / 100 ) - 100 ))" "${ratio1:0:$(( ${#ratio1} - 4 ))}" "${ratio1:$(( ${#ratio1} - 4 ))}")"
                else
                    ratio1="$(( ( ( 10000 * ${A[0]//./} ) / ${A[2]//./} ) ))"
                    printf0 44:"$(printf 'parallel is %s%% faster than forkrun (%s.%sx)' "$(( ( $ratio1 / 100 ) - 100 ))" "${ratio1:0:$(( ${#ratio1} - 4 ))}" "${ratio1:$(( ${#ratio1} - 4 ))}")"
                fi
            fi
            printf '\n'
    done
done


# RESULTS
:<<'EOF'
||-----------------------------------------------------------------||
||-----------------------RUN_TIME_IN_SECONDS-----------------------||
||-----------------------------------------------------------------||



||--------------------------------------------------------NUM_CHECKSUMS=10--------------------------------------------------------------------------------|| 

(algorithm)       (forkrun)        (xargs)        (parallel)    (relative performance vs xargs)                         (relative performance vs parallel)                
------------    ------------    ------------    ------------    --------------------------------                        --------------------------------                  
sha1sum         0.0222534505    0.0016553424    0.1639293264    xargs is 1244% faster than forkrun (13.4434x)   forkrun is 636% faster than parallel (7.3664x)
sha256sum       0.0224321113    0.0019225847    0.1643929194    xargs is 1066% faster than forkrun (11.6676x)   forkrun is 632% faster than parallel (7.3284x)
sha512sum       0.0224833227    0.0019746615    0.1641596578    xargs is 1038% faster than forkrun (11.3859x)   forkrun is 630% faster than parallel (7.3013x)
sha224sum       0.0224760428    0.0019354711    0.1641195802    xargs is 1061% faster than forkrun (11.6126x)   forkrun is 630% faster than parallel (7.3019x)
sha384sum       0.0224642114    0.0019470189    0.1642083240    xargs is 1053% faster than forkrun (11.5377x)   forkrun is 630% faster than parallel (7.3097x)
md5sum          0.0224252539    0.0018934479    0.1644324023    xargs is 1084% faster than forkrun (11.8436x)   forkrun is 633% faster than parallel (7.3324x)
sum -s          0.0220311442    0.0014830763    0.1643778599    xargs is 1385% faster than forkrun (14.8550x)   forkrun is 646% faster than parallel (7.4611x)
sum -r          0.0220596278    0.0014955193    0.1641833856    xargs is 1375% faster than forkrun (14.7504x)   forkrun is 644% faster than parallel (7.4427x)
cksum           0.0224862719    0.0018678214    0.1643340151    xargs is 1103% faster than forkrun (12.0387x)   forkrun is 630% faster than parallel (7.3081x)
b2sum           0.0220968347    0.0015863721    0.1637067688    xargs is 1292% faster than forkrun (13.9291x)   forkrun is 640% faster than parallel (7.4086x)
cksum -a sm3    0.0224746202    0.0019623188    0.1653221060    xargs is 1045% faster than forkrun (11.4530x)   forkrun is 635% faster than parallel (7.3559x)



||--------------------------------------------------------NUM_CHECKSUMS=100--------------------------------------------------------------------------------|| 

(algorithm)       (forkrun)        (xargs)        (parallel)    (relative performance vs xargs)                         (relative performance vs parallel)                
------------    ------------    ------------    ------------    --------------------------------                        --------------------------------                  
sha1sum         0.0615108225    0.0925538512    0.2165036578    forkrun is 50% faster than xargs (1.5046x)      forkrun is 251% faster than parallel (3.5197x)
sha256sum       0.1032652783    0.1889380574    0.2482839869    forkrun is 82% faster than xargs (1.8296x)      forkrun is 140% faster than parallel (2.4043x)
sha512sum       0.0781284626    0.1308450793    0.2286306496    forkrun is 67% faster than xargs (1.6747x)      forkrun is 192% faster than parallel (2.9263x)
sha224sum       0.1034834870    0.1887813322    0.2483117295    forkrun is 82% faster than xargs (1.8242x)      forkrun is 139% faster than parallel (2.3995x)
sha384sum       0.0780973690    0.1305682476    0.2288789023    forkrun is 67% faster than xargs (1.6718x)      forkrun is 193% faster than parallel (2.9306x)
md5sum          0.0764524841    0.1269247738    0.2276439758    forkrun is 66% faster than xargs (1.6601x)      forkrun is 197% faster than parallel (2.9775x)
sum -s          0.0298585324    0.0206090565    0.1964410383    xargs is 44% faster than forkrun (1.4488x)      forkrun is 557% faster than parallel (6.5790x)
sum -r          0.0767527080    0.1288134217    0.2286213547    forkrun is 67% faster than xargs (1.6782x)      forkrun is 197% faster than parallel (2.9786x)
cksum           0.0283167635    0.0154324341    0.1957605173    xargs is 83% faster than forkrun (1.8348x)      forkrun is 591% faster than parallel (6.9132x)
b2sum           0.0706542464    0.1143294604    0.2231340505    forkrun is 61% faster than xargs (1.6181x)      forkrun is 215% faster than parallel (3.1581x)
cksum -a sm3    0.1713636662    0.3437932248    0.3053360030    forkrun is 100% faster than xargs (2.0062x)     forkrun is 78% faster than parallel (1.7818x)



||--------------------------------------------------------NUM_CHECKSUMS=1000--------------------------------------------------------------------------------|| 

(algorithm)       (forkrun)        (xargs)        (parallel)    (relative performance vs xargs)                         (relative performance vs parallel)                
------------    ------------    ------------    ------------    --------------------------------                        --------------------------------                  
sha1sum         0.2801649903    0.8460509787    0.4101929954    forkrun is 201% faster than xargs (3.0198x)     forkrun is 46% faster than parallel (1.4641x)
sha256sum       0.5678104824    1.7440357799    0.6008062592    forkrun is 207% faster than xargs (3.0715x)     forkrun is 5% faster than parallel (1.0581x)
sha512sum       0.3872871103    1.2043758396    0.4803434806    forkrun is 210% faster than xargs (3.1097x)     forkrun is 24% faster than parallel (1.2402x)
sha224sum       0.5576667495    1.7658578190    0.6086087740    forkrun is 216% faster than xargs (3.1665x)     forkrun is 9% faster than parallel (1.0913x)
sha384sum       0.3864215964    1.2070835369    0.4808070493    forkrun is 212% faster than xargs (3.1237x)     forkrun is 24% faster than parallel (1.2442x)
md5sum          0.3765466161    1.1662194441    0.4738973084    forkrun is 209% faster than xargs (3.0971x)     forkrun is 25% faster than parallel (1.2585x)
sum -s          0.0802226022    0.1845034156    0.2770125788    forkrun is 129% faster than xargs (2.2998x)     forkrun is 245% faster than parallel (3.4530x)
sum -r          0.4120334167    1.1859286033    0.4778189380    forkrun is 187% faster than xargs (2.8782x)     forkrun is 15% faster than parallel (1.1596x)
cksum           0.0640634743    0.1335233825    0.2674417961    forkrun is 108% faster than xargs (2.0842x)     forkrun is 317% faster than parallel (4.1746x)
b2sum           0.3665638608    1.0600934594    0.4531968907    forkrun is 189% faster than xargs (2.8919x)     forkrun is 23% faster than parallel (1.2363x)
cksum -a sm3    0.9909217356    3.2132617486    0.9271151218    forkrun is 224% faster than xargs (3.2426x)     parallel is 6% faster than forkrun (1.0688x)



||--------------------------------------------------------NUM_CHECKSUMS=10000--------------------------------------------------------------------------------|| 

(algorithm)       (forkrun)        (xargs)        (parallel)    (relative performance vs xargs)                         (relative performance vs parallel)                
------------    ------------    ------------    ------------    --------------------------------                        --------------------------------                  
sha1sum         0.7422190967    1.8590699950    1.5771322948    forkrun is 150% faster than xargs (2.5047x)     forkrun is 112% faster than parallel (2.1248x)
sha256sum       1.5060250844    3.8438164785    3.011755419     forkrun is 155% faster than xargs (2.5522x)     forkrun is 99% faster than parallel (1.9998x)
sha512sum       1.0623511522    2.6429729001    2.1418995588    forkrun is 148% faster than xargs (2.4878x)     forkrun is 101% faster than parallel (2.0161x)
sha224sum       1.5019801779    3.7925587301    2.9876361720    forkrun is 152% faster than xargs (2.5250x)     forkrun is 98% faster than parallel (1.9891x)
sha384sum       1.0379101399    2.6186776838    2.1301994834    forkrun is 152% faster than xargs (2.5230x)     forkrun is 105% faster than parallel (2.0523x)
md5sum          1.0044442991    2.5260769766    2.0735571881    forkrun is 151% faster than xargs (2.5149x)     forkrun is 106% faster than parallel (2.0643x)
sum -s          0.1820129360    0.4156542137    0.5556879383    forkrun is 128% faster than xargs (2.2836x)     forkrun is 205% faster than parallel (3.0530x)
sum -r          1.0208828587    2.5751372755    2.1023561111    forkrun is 152% faster than xargs (2.5224x)     forkrun is 105% faster than parallel (2.0593x)
cksum           0.1393235305    0.2973036305    0.5560366667    forkrun is 113% faster than xargs (2.1339x)     forkrun is 299% faster than parallel (3.9909x)
b2sum           0.9257819100    2.3117826413    1.9118161726    forkrun is 149% faster than xargs (2.4971x)     forkrun is 106% faster than parallel (2.0650x)
cksum -a sm3    2.7357195803    6.9289504979    5.3322363836    forkrun is 153% faster than xargs (2.5327x)     forkrun is 94% faster than parallel (1.9491x)



||--------------------------------------------------------NUM_CHECKSUMS=100000--------------------------------------------------------------------------------|| 

(algorithm)       (forkrun)        (xargs)        (parallel)    (relative performance vs xargs)                         (relative performance vs parallel)                
------------    ------------    ------------    ------------    --------------------------------                        --------------------------------                  
sha1sum         1.1887103823    1.9448609561    5.1713720646    forkrun is 63% faster than xargs (1.6361x)      forkrun is 335% faster than parallel (4.3504x)
sha256sum       2.3099104823    3.9477093925    6.7813421334    forkrun is 70% faster than xargs (1.7090x)      forkrun is 193% faster than parallel (2.9357x)
sha512sum       1.6638213981    2.7640951179    5.8141292662    forkrun is 66% faster than xargs (1.6612x)      forkrun is 249% faster than parallel (3.4944x)
sha224sum       2.2999315747    3.9443101272    6.7801000775    forkrun is 71% faster than xargs (1.7149x)      forkrun is 194% faster than parallel (2.9479x)
sha384sum       1.6580899784    2.7575194406    5.7915458913    forkrun is 66% faster than xargs (1.6630x)      forkrun is 249% faster than parallel (3.4929x)
md5sum          1.4521753740    2.5705767466    5.7416163298    forkrun is 77% faster than xargs (1.7701x)      forkrun is 295% faster than parallel (3.9538x)
sum -s          0.3495215528    0.5510113842    3.9639472210    forkrun is 57% faster than xargs (1.5764x)      forkrun is 1034% faster than parallel (11.3410x)
sum -r          1.4391527927    2.6018136698    5.7517653067    forkrun is 80% faster than xargs (1.8078x)      forkrun is 299% faster than parallel (3.9966x)
cksum           0.2897134000    0.4502675263    3.9705733100    forkrun is 55% faster than xargs (1.5541x)      forkrun is 1270% faster than parallel (13.7051x)
b2sum           1.4579099665    2.4313927221    5.5184188502    forkrun is 66% faster than xargs (1.6677x)      forkrun is 278% faster than parallel (3.7851x)
cksum -a sm3    4.2353032483    7.2793010655    9.4345548364    forkrun is 71% faster than xargs (1.7187x)      forkrun is 122% faster than parallel (2.2275x)



||--------------------------------------------------------NUM_CHECKSUMS=523216--------------------------------------------------------------------------------|| 

(algorithm)       (forkrun)        (xargs)        (parallel)    (relative performance vs xargs)                         (relative performance vs parallel)                
------------    ------------    ------------    ------------    --------------------------------                        --------------------------------                  
sha1sum         2.1575105903    2.2305427909    20.525304139    forkrun is 3% faster than xargs (1.0338x)       forkrun is 851% faster than parallel (9.5134x)
sha256sum       3.9899657122    4.6285643124    20.787470871    forkrun is 16% faster than xargs (1.1600x)      forkrun is 420% faster than parallel (5.2099x)
sha512sum       3.0032874696    3.2898729946    20.488153715    forkrun is 9% faster than xargs (1.0954x)       forkrun is 582% faster than parallel (6.8219x)
sha224sum       3.9834935823    4.5956923250    20.652664582    forkrun is 15% faster than xargs (1.1536x)      forkrun is 418% faster than parallel (5.1845x)
sha384sum       2.9483350640    3.2528261031    20.473145964    forkrun is 10% faster than xargs (1.1032x)      forkrun is 594% faster than parallel (6.9439x)
md5sum          2.3177881276    2.6731640952    20.419467464    forkrun is 15% faster than xargs (1.1533x)      forkrun is 780% faster than parallel (8.8098x)
sum -s          0.8327583345    1.1131111934    20.033729873    forkrun is 33% faster than xargs (1.3366x)      forkrun is 2305% faster than parallel (24.0570x)
sum -r          2.2571877616    2.6794892402    20.450460537    forkrun is 18% faster than xargs (1.1870x)      forkrun is 806% faster than parallel (9.0601x)
cksum           0.7653010927    1.1095221662    19.987581085    forkrun is 44% faster than xargs (1.4497x)      forkrun is 2511% faster than parallel (26.1172x)
b2sum           2.5989495509    2.8008142323    20.502623047    forkrun is 7% faster than xargs (1.0776x)       forkrun is 688% faster than parallel (7.8888x)
cksum -a sm3    7.1213390589    8.5324344607    20.870831885    forkrun is 19% faster than xargs (1.1981x)      forkrun is 193% faster than parallel (2.9307x)
EOF
