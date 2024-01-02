
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

"${testParallelFlag:=true}"

mkdir -p "${hfdir}"/{results,file_lists}

for kk in {1..6}; do
    find "${findDir}" -type f | head -n $(( 10 ** $kk )) >"${hfdir}"/file_lists/f${kk}
done

for kk in {1..6}; do 
     printf '\n-------------------------------- %s values --------------------------------\n\n' $(wc -l <"${hfdir}"/file_lists/f${kk}); 

     for c in  sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3"; do 
         printf '\n---------------- %s ----------------\n\n' "$c"; 

         hyperfine -w 1 -i --shell /usr/bin/bash --parameter-list cmd 'source '"${PWD}"'/forkrun.bash && forkrun --','xargs -P '"$(nproc)"' -d $'"'"'\n'"'"' --' --export-json ""${hfdir}"/results/forkrun.${c// /_}.f${kk}.hyperfine.results" --style=full --setup 'shopt -s extglob' --prepare 'renice --priority -20 --pid $$' '{cmd} '"${c}"' <'"${hfdir}"'/file_lists/f'"${kk}" 

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


printf '%.18s   \t' alg '    |    ' 'num vals (stdin):' $(wc -l <"${hfdir}/file_lists/f1") '        ' '        ' '        ' '        ' '        '$(wc -l <"${hfdir}/file_lists/f2") '        ' '        ' '        ' '        ' '        '$(wc -l <"${hfdir}/file_lists/f3") '        ' '        ' '        ' '        ' '        '$(wc -l <"${hfdir}/file_lists/f4") '        ' '        ' '        ' $(wc -l <"${hfdir}/file_lists/f5") '        ' '        ' '        ' '        ' '        '$(wc -l <"${hfdir}/file_lists/f6") 
printf '\n\n'
shopt -s extglob
declare +i -a A
for c in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3"; do
printf '%0.11s    \t' "$c"
for kk in {1..6}; do
mapfile -t A < <(grep -F "$t" < "${hfdir}"/results/forkrun."${c// /_}".f${kk}.hyperfine.results | sed -E s/'^.*\:'//)
printf '%0.12s\t' "${A[@]}"
A=("${A[@]//[ \,]/}")
if (( ${#A[0]} < ${#A[1]} )); then
    A=("${A[0]:0:${#A[0]}}" "${A[1]:0:${#A[0]}}")
else
    A=("${A[0]:0:${#A[1]}}" "${A[1]:0:${#A[1]}}")
fi
A=("${A[@]##*([0\.\(\:\)\,])}")
A=("${A[@]//./}")
if (( ${A[0]} < ${A[1]} )); then
    ratio="$(( ( ( 10000 * ${A[1]//./} ) / ${A[0]//./} ) ))"
    printf 'forkrun is %s%% faster (%s.%sx) \t' "$(( ( $ratio / 100 ) - 100 ))" "${ratio:0:$(( ${#ratio} - 4 ))}" "${ratio:$(( ${#ratio} - 4 ))}"
elif (( ${A[0]} > ${A[1]} )); then
    ratio="$(( ( ( 10000 * ${A[0]//./} ) / ${A[1]//./} ) ))"
    printf 'xargs is %s%% faster (%s.%sx)   \t' "$(( ( $ratio / 100 ) - 100 ))" "${ratio:0:$(( ${#ratio} - 4 ))}" "${ratio:$(( ${#ratio} - 4 ))}" 
else
    printf 'forkrun and xargs are equal        \t'
fi
printf '\t'
done
printf '\n'
done


# RESULTS
:<<'EOF'

alg         |           num vals (stdin):       10                                                                              100                                                                             1000                                                                            10000                                                           100000                                                                                  523216   

sha1sum          0.022897558     0.002166420    xargs is 956% faster (10.5693x)                  0.062360921     0.095800445    forkrun is 53% faster (1.5362x)                  0.322940073     0.860009300    forkrun is 166% faster (2.6630x)                 0.790835323     1.860930251    forkrun is 135% faster (2.3531x)                 1.224702680     1.977549328    forkrun is 61% faster (1.6147x)                  2.190113137     2.393303680    forkrun is 9% faster (1.0927x) 
sha256sum        0.022690787     0.002060012    xargs is 1001% faster (11.0148x)                 0.104255117     0.192510309    forkrun is 84% faster (1.8465x)                  0.563033554     1.807716679    forkrun is 221% faster (3.2106x)                 1.562373870     3.940632164    forkrun is 152% faster (2.5222x)                 2.382918501     4.180151309    forkrun is 75% faster (1.7542x)                  4.078675215     4.875776022    forkrun is 19% faster (1.1954x) 
sha512sum        0.022754313     0.002111534    xargs is 977% faster (10.7762x)                  0.079125365     0.133660000    forkrun is 68% faster (1.6892x)                  0.442993946     1.233439434    forkrun is 178% faster (2.7843x)                 1.052927197     2.738166180    forkrun is 160% faster (2.6005x)                 1.724571548     2.816160723    forkrun is 63% faster (1.6329x)                  3.035530448     3.369094943    forkrun is 10% faster (1.1098x) 
sha224sum        0.022740575     0.002124984    xargs is 970% faster (10.7015x)                  0.104600094     0.189343060    forkrun is 81% faster (1.8101x)                  0.638507564     1.756865446    forkrun is 175% faster (2.7515x)                 1.565599915     3.913768903    forkrun is 149% faster (2.4998x)                 2.328941683     4.133394300    forkrun is 77% faster (1.7747x)                  4.018339837     4.858119909    forkrun is 20% faster (1.2089x) 
sha384sum        0.023112473     0.002146010    xargs is 976% faster (10.7699x)                  0.079882899     0.131020154    forkrun is 64% faster (1.6401x)                  0.402631212     1.200516963    forkrun is 198% faster (2.9816x)                 1.060589184     2.722283144    forkrun is 156% faster (2.5667x)                 1.694193628     2.838735773    forkrun is 67% faster (1.6755x)                  3.073523590     3.401898443    forkrun is 10% faster (1.1068x) 
md5sum           0.022847943     0.002050732    xargs is 1014% faster (11.1413x)                 0.078774083     0.129412855    forkrun is 64% faster (1.6428x)                  0.418730951     1.163952784    forkrun is 177% faster (2.7797x)                 1.026350707     2.623692918    forkrun is 155% faster (2.5563x)                 1.488352572     2.581215641    forkrun is 73% faster (1.7342x)                  2.333199986     2.735046664    forkrun is 17% faster (1.1722x) 
sum -s           0.022390876     0.001660054    xargs is 1248% faster (13.4880x)                 0.030087207     0.021349039    xargs is 40% faster (1.4093x)                    0.085035415     0.184441999    forkrun is 116% faster (2.1690x)                 0.198295012     0.415107938    forkrun is 109% faster (2.0933x)                 0.375067913     0.552020779    forkrun is 47% faster (1.4717x)                  0.829455086     1.126618969    forkrun is 35% faster (1.3582x) 
sum -r           0.022177756     0.001608458    xargs is 1278% faster (13.7882x)                 0.076915226     0.132008413    forkrun is 71% faster (1.7162x)                  0.419561219     1.183147583    forkrun is 181% faster (2.8199x)                 1.031639377     2.574521561    forkrun is 149% faster (2.4955x)                 1.493508268     2.693818524    forkrun is 80% faster (1.8036x)                  2.259332241     2.806269216    forkrun is 24% faster (1.2420x) 
cksum            0.022976104     0.002063765    xargs is 1013% faster (11.1331x)                 0.028767780     0.015846436    xargs is 81% faster (1.8154x)                    0.070022212     0.134321870    forkrun is 91% faster (1.9182x)                  0.149270862     0.301539145    forkrun is 102% faster (2.0200x)                 0.298164469     0.452108718    forkrun is 51% faster (1.5163x)                  0.763364711     1.110653253    forkrun is 45% faster (1.4549x) 
b2sum            0.022540379     0.001739910    xargs is 1195% faster (12.9549x)                 0.071399194     0.115159163    forkrun is 61% faster (1.6128x)                  0.376410111     1.083341861    forkrun is 187% faster (2.8780x)                 0.966089235     2.376990059    forkrun is 146% faster (2.4604x)                 1.515115203     2.465370805    forkrun is 62% faster (1.6271x)                  2.650145532     2.907172633    forkrun is 9% faster (1.0969x) 
cksum -a sm      0.022863460     0.002101006    xargs is 988% faster (10.8821x)                  0.172344731     0.343810034    forkrun is 99% faster (1.9948x)                  1.004685180     3.225545571    forkrun is 221% faster (3.2105x)                 2.796767350     7.086051000    forkrun is 153% faster (2.5336x)                 4.336208735     7.508517476    forkrun is 73% faster (1.7315x)                  7.244091051     8.772369078    forkrun is 21% faster (1.2109x)
EOF
