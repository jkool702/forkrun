( 
# source frun 
shopt -s globstar
printf -v frun_path '%s\n' "${BASH_SOURCE[0]%\/*}"/**/frun.{new.,}bash
. "${frun_path%%$'\n'*}"

# setup test files
yes $'\n'|head -n 100000000 >f1
seq 100000000 >f2
find / -type f >f3

# setup tests
F=(f1 f2 f3)
G=('' '-o' '-u' '-o -u')
C=(':' 'echo' "printf '%s\n'")

N=$(( ${#F[@]} * ${#G[@]} * ${#C[@]} * 4 ))
K=0

## RUN BENCHMARK
for Fk in "${F[@]}"; do
for Gk in "${G[@]}"; do
for Ck in "${C[@]}"; do

	((K++)); echo; echo "($K): time frun $Gk $Ck <$Fk >/dev/null"
time frun $Gk $Ck <$Fk >/dev/null

((K++)); echo; echo "($K): time frun $Gk $Ck <$Fk | wc -l"
time frun $Gk $Ck <$Fk | wc -l

((K++)); echo; echo "($K): time { cat $Fk | frun $Gk $Ck >/dev/null; }"
time { cat $Fk | frun $Gk $Ck >/dev/null; }

((K++)); echo; echo "($K): time { cat $Fk | frun $Gk $Ck | wc -l; }"
time { cat $Fk | frun $Gk $Ck | wc -l; }

done
done
done

# stats on input files
printf '\n\n-----------------------------\nINPUTS DATA STATS\n\n'; 
for f in f1 f2 f3; do
printf '\n\nNAME: %s\nSIZE: %s bytes\nLINE COUNT: %s lines\n' "$f" "$(du -d 0 -b "$f" | sed -E s/'[ \t].*$//')" "$(wc -l <"$f")"
done

) | tee benchmark.out

{ for f in real user sys; do grep -E '^'"$f" <benchmark.out | sed -E 's/^'"$f"'[ \t]*//'| { declare -i v=0;  while read -r nn; do m=${nn%%m*}; s=${nn#*m}; s=${s//[^0-9]/}; v=$(( v + (60000 * 10#0${m}) + 10#0${s} )); done; printf '\ntotal %s = %s us\n' "$f" "$v" >&$fd2; }; done; } {fd2}>&2

