> source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/mySplit.bash)
A="$(printf '%.0s'"$(echo $(dd if=/dev/urandom bs=4096 count=1 | hexdump) | sed -E s/'^(.{4096}).*$'/'\1'/)"'\n' {1..10000})"
{
for nChars in {0..32} {34..64..2} {68..128..4} {136..256..8} {272..512..16} {544..1024..32} {1088..2048..64} {2176..4096..128}; do
a="$(echo "${A}" | sed -E s/'^(.{'${nChars}'}).*$'/'\1'/)"
nChars32="$(( 32 * ( 1 + ${nChars} ) ))"
d1=$(( ${#nChars32} - 1 ))
d2=$(( ${#nChars32} - ${#nChars} ))

printf '\n\n STANDARD READ : %s bytes/line (%s byte/read)  '"$(printf '%.0s ' $(seq 1 $d1))"'\t' "$(( 1 + ${nChars} ))" 1
{ time { echo "$a" | while read -r; do echo "$REPLY"; done | wc -l; } >/dev/null; } 2>&1 | tr $'\n' $'\t' | sed -E s/'^[ \t]*'//; 
printf '\n mySplit-1P-1L : %s bytes/line (%s bytes/read) '"$(printf '%.0s ' $(seq 1 $d2))"'\t' "$(( 1 + ${nChars} ))" "$(( 1 + ${nChars} ))"
{ time { echo "$a" | mySplit 1 1 2>/dev/null | wc -l; } >/dev/null; } 2>&1 | tr $'\n' $'\t' | sed -E s/'^[ \t]*'//; 
printf '\n mySplit-4P-1L : %s bytes/line (%s bytes/read) '"$(printf '%.0s ' $(seq 1 $d2))"'\t' "$(( 1 + ${nChars} ))" "$(( 1 + ${nChars} ))"
{ time { echo "$a" | mySplit 1 4 2>/dev/null | wc -l; } >/dev/null; } 2>&1 | tr $'\n' $'\t' | sed -E s/'^[ \t]*'//; 
printf '\n mySplit-1P-32L: %s bytes/line (%s bytes/read) \t' "$(( 1 + ${nChars} ))" "${nChars32}"
{ time { echo "$a" | mySplit 32 1 2>/dev/null | wc -l; } >/dev/null; } 2>&1 | tr $'\n' $'\t' | sed -E s/'^[ \t]*'//; 
printf '\n mySplit-4P-32L: %s bytes/line (%s bytes/read) \t' "$(( 1 + ${nChars} ))" "$(( 32 * ( 1 + ${nChars} ) ))"
{ time { echo "$a" | mySplit 32 4 2>/dev/null | wc -l; } >/dev/null; } 2>&1 | tr $'\n' $'\t' | sed -E s/'^[ \t]*'//; 
done
} | tee | tee /tmp/.mySplit.speedtest3

