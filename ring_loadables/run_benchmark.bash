(
(
# source frun 
shopt -s globstar
shopt -s extglob
printf -v frun_path '%s\n' {.,"${BASH_SOURCE[0]%\/*}"}/**/frun.{new.,}bash
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

getCPU() {
local t_real t_user t_sys cpu

{
until [[ ${t_real} ]]; do read -r -u $fd_time _ t_real; done
read -r -u $fd_time _ t_user
read -r -u $fd_time _ t_sys
} {fd_time}<./.time

t_real=${t_real//[.s:]/}
t_user=${t_user//[.s:]/}
t_sys=${t_sys//[.s:]/}

cpu=$(( 1000 * ( 60000 * ( 10#0${t_user%m*} + 10#0${t_sys%m*} ) + 10#0${t_user#*m} + 10#0${t_sys#*m} ) /  ( 60000 * 10#0${t_real%m*} + 10#0${t_real#*m} ) ))

printf '\nCPU UTILIZATION: %0.1d.%0.3d / %d\n' "${cpu:0:$((${#cpu}-3))}" "${cpu:$((${#cpu}-3))}" "$(nproc)"
printf '\n-----------------------------------------\n'

exec {fd_time}<&-
}

## RUN BENCHMARK
for Fk in "${F[@]}"; do
for Gk in "${G[@]}"; do
for Ck in "${C[@]}"; do

((K++)); echo; echo "($K): time frun $Gk $Ck <$Fk >/dev/null"
{ time { frun  $Gk $Ck <$Fk >/dev/null} 2>&$fd2; }; } 2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
getCPU

((K++)); echo; echo "($K): time frun $Gk $Ck <$Fk | wc -l"
{ time { frun  $Gk $Ck <$Fk 2>&$fd2 | wc -l; } 1>&$fd1 ; } 2>&1 | sed -zE 's/^.*real/real/' | tee ./.time
getCPU

((K++)); echo; echo "($K): time { cat $Fk | frun $Gk $Ck >/dev/null; }"
{ time { cat $Fk | frun  $Gk $Ck >/dev/null 2>&$fd2; }; } 2>&1 | sed -zE 's/^.*real/real/' |  tee ./.time
getCPU

((K++)); echo; echo "($K): time { cat $Fk | frun $Gk $Ck | wc -l; }"
{ time { cat $Fk | frun  $Gk $Ck  2>&$fd2 | wc -l; } 1>&$fd1; } 2>&1 | sed -zE 's/^.*real/real/' |  tee ./.time
getCPU

done
done
done

# stats on input files
printf '\n\n-----------------------------\nINPUT DATA STATS\n\n';
for f in f1 f2 f3; do
printf '\n\nNAME: %s\nSIZE: %s bytes\nLINE COUNT: %s lines\n' "$f" "$(du -d 0 -b "$f" | sed -E s/'[ \t].*$//')" "$(wc -l <"$f")"
done


) | tee benchmark.out

unset outA;
declare -A outA;
for f in real user sys; do
	{ 
		{
		declare -i v=0;  
		while read -r -u $fd0 nn; do 
			m=${nn%%m*}; 
			s=${nn#*m}; 
			s=${s//[^0-9]/};
			v=$(( v + (60000 * 10#0${m}) + 10#0${s} )); 
		done; 
		outA[$f]="$v"
		} {fd2}>&2 {fd0}<&0
	} < <(grep -E '^'"$f" <benchmark.out | sed -E 's/^'"$f"'[ \t]*//')
done

for f in "${!outA[@]}"; do
	v="${outA[$f]}"
	printf '\ntotal %s = %s us\n' "$f" "$v" | tee -a benchmark.out >&$fd2
done

cpu=$(( 1000 * ( 10#0${outA[user]} + 10#0${outA[sys]} ) / 10#0${outA[real]} ))
printf '\n\nOVERALL CPU UTILIZATION: %d.%0.3d / %s\n\n' "${cpu:0:$((${#cpu}-3))}" "${cpu:$((${#cpu}-3))}" "$(nproc)" |  tee -a benchmark.out >&$fd2

\rm f1 f2 f3
) {fd1}>&1 {fd2}>&2
