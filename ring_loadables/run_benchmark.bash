. "$(find ./ -type f -name frun.bash | head -n 1)"
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
done
done
done

