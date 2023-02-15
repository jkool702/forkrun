testPath="$(mktemp -d -p $(pwd) -t .forkrun.unit-tests.XXXXXXXXX)"
cd "${testPath}"

{
echo '#!/bin/bash'
echo 'cd "'"${testPath}"'"'
[[ -f /mnt/ramdisk/forkrun/forkrun.bash ]] && echo 'source /mnt/ramdisk/forkrun/forkrun.bash' || echo 'source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)'
for nn in $(seq 1 $(( 10 * $(nproc) + 1 ))); do
	echo 'echo "'"${nn}"'" > "'"${testPath}/${nn}"'"'
done

for np in $(( $(nproc) - 2 )) $(( 10 * $(nproc) + 1 )); do
	echo $'\n'seq\ 1\ ${np}\ \|\ forkrun\ {,-k\ ,-n\ }{,-l1\ }{,-j$(( $(nproc) - 1 ))\ }{,-t\ /tmp\ }{,-d\ 3\ }{,--\ }{sha1sum,sha256sum,echo,printf\ '"'"'"'%s\n'"'"'"'}\ \|\ wc\ -l\ \|\ grep\ -qx\ ${np}\ \&\&\ echo\ \"PASS\"\ \|\|\ echo\ \"FAIL\ \<-----\"$'\n' | sed -E s/^'(.*)( \| wc -l.*)$'/'\{ echo -n "\1 : "; \1\2; \} \| tee -a .\/forkrun.unit-tests.log'/ 
	wait
        echo $'\n'seq\ 1\ ${np}\ \|\ forkrun\ -i\ {,-k\ ,-n\ }{,-l1\ }{,-j$(( $(nproc) - 1 ))\ }{,-t\ /tmp\ }{,-d\ 3\ }{,--\ }{sha1sum,sha256sum,echo,printf\ \"\'\"\'%s\\n\'\"\'\"}\ \{\}\ \|\ wc\ -l\ \|\ grep\ -qx\ ${np}\ \&\&\ echo\ \"PASS\"\ \|\|\ echo\ \"FAIL \<-----\"$'\n' | sed -E s/^'(.*)( \| wc -l.*)$'/'\{ echo -n "\1 : "; \1\2; \} \| tee -a .\/forkrun.unit-tests.log'/
	wait
done | grep -E '[a-ZA-Z0-9]+'
} > "${testPath}/forkrun.run-unit-tests.bash"



chmod +x "${testPath}/forkrun.run-unit-tests.bash"

"${testPath}/forkrun.run-unit-tests.bash" 2>/dev/null

printf '%s\n' '' 'TESTS COMPLETE!' '' 'SUMMARY:'  '' 'PASSED: '"$(cat "${testPath}/forkrun.unit-tests.log" | grep 'PASS' | wc -l)" 'FAILED '"$(cat "${testPath}/forkrun.unit-tests.log" | grep 'FAIL' | wc -l)" ''

cd "$OLDPWD"

[[ -f ./forkrun.unit-tests.log ]] && cat ./forkrun.unit-tests.log >> ./forkrun.unit-tests.log.old && rm -f ./forkrun.unit-tests.log
cp "${testPath}/forkrun.unit-tests.log" ./

