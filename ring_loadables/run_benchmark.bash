. "$(find ./ -type f -maxdepth 1 -name frun.new.bash | head -n 1)"

yes $'\n'|head -n 100000000 >f1
seq 100000000 >f2
find / -type f >f3

F=(f1 f2 f3)
G=('' '-o' '-u' '-o -u')
C=(':' 'echo' "printf '%s\n'")

## RUN BENCHMARK
for Fk in "${F[@]}"; do
for Gk in "${G[@]}"; do
for Ck in "${C[@]}"; do

echo; echo "time frun $Gk $Ck <$Fk >/dev/null"
time frun $Gk $Ck <$Fk >/dev/null

echo; echo "time frun $Gk $Ck <$Fk | wc -l"
time frun $Gk $Ck <$Fk | wc -l

echo; echo "time { cat $Fk | frun $Gk $Ck >/dev/null; }"
time { cat $Fk | frun $Gk $Ck >/dev/null; }

echo; echo "time { cat $Fk | frun $Gk $Ck | wc -l; }"
time { cat $Fk | frun $Gk $Ck | wc -l; }

done
done
done

# stats on input files
printf '\n\n-----------------------------\nINPUTS DATA STATS\n\n'; 
for f in f1 f2 f3; do
printf '\n\nNAME: %s\nSIZE: %s bytes\nLINE COUNT: %s lines\n' "$f" "$(du -d 0 -b "$f" | sed -E s/'[ \t].*$//')" "$(wc -l <"$f")"
done

