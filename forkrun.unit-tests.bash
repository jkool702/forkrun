testPath="$(mktemp -d -p $(pwd) -t .forkrun.unit-tests.XXXXXXXXX)"
cd "${testPath}"

{
echo '#!/bin/bash'
echo 'cd "'"${testPath}"'"'
echo 'source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)'
for nn in $(seq 1 $(( 10 * $(nproc) + 1 ))); do
	echo 'echo "'"${nn}"'" > "'"${testPath}/${nn}"'"'
done

echo \[\[\ \$\(seq\ 1\ $(( $(nproc) - 2 ))\ \|\ forkrun\ {,-k\ ,-n\ }{,-l1\ }{,-j$(( $(nproc) - 1 ))\ }{,-t\ /tmp\ }{,-d\ 3\ }{,--\ }{sha1sum,sha256sum,echo,printf\ '"'"'"'%s\n'"'"'"'}\ \|\ wc\ -l\)\ ==\ $(( $(nproc) - 2 ))\ \]\]\ \&\&\ echo\ \"SUCCESS\"\ \|\|\ echo\ \"FAILURE\ \<-----\"$'\n' | sed -E s/^'(.*forkrun )(.*)( \| wc -l.*)$'/'\{ echo -n "forkrun \2 : "; \1\2\3; \} \| tee -a .\/forkrun.unit-tests.log'/
echo \[\[\ \$\(seq\ 1\ $(( 10 * $(nproc) + 1 ))\ \|\ forkrun\ {,-k\ ,-n\ }{,-l1\ }{,-j$(( $(nproc) - 1 ))\ }{,-t\ /tmp\ }{,-d\ 3\ }{,--\ }{sha1sum,sha256sum,echo,printf\ '"'"'"'%s\n'"'"'"'}\ \|\ wc\ -l\)\ ==\ $(( 10 * $(nproc) + 1 ))\ \]\]\ \&\&\ echo\ \"SUCCESS\"\ \|\|\ echo\ \"FAILURE\ \<-----\"$'\n' | sed -E s/^'(.*forkrun )(.*)( \| wc -l.*)$'/'\{ echo -n "forkrun \2 : "; \1\2\3; \} \| tee -a .\/forkrun.unit-tests.log'/
echo \[\[\ \$\(seq\ 1\ $(( $(nproc) - 2 ))\ \|\ forkrun\ -i\ {,-k\ ,-n\ }{,-l1\ }{,-j$(( $(nproc) - 1 ))\ }{,-t\ /tmp\ }{,-d\ 3\ }{,--\ }{sha1sum,sha256sum,echo,printf\ '"'"'"'%s\n'"'"'"'}\ {}\ \|\ wc\ -l\)\ ==\ $(( $(nproc) - 2 ))\ \]\]\ \&\&\ echo\ \"SUCCESS\"\ \|\|\ echo\ \"FAILURE\ \<-----\"$'\n' | sed -E s/^'(.*forkrun )(.*)( \| wc -l.*)$'/'\{ echo -n "forkrun \2 : "; \1\2\3; \} \| tee -a .\/forkrun.unit-tests.log'/
echo \[\[\ \$\(seq\ 1\ $(( 10 * $(nproc) + 1 ))\ \|\ forkrun\ -i\ {,-k\ ,-n\ }{,-l1\ }{,-j$(( $(nproc) - 1 ))\ }{,-t\ /tmp\ }{,-d\ 3\ }{,--\ }{sha1sum,sha256sum,echo,printf\ '"'"'"'%s\n'"'"'"'}\ {}| \|\ wc\ -l\)\ ==\ $(( 10 * $(nproc) + 1 ))\ \]\]\ \&\&\ echo\ \"SUCCESS\"\ \|\|\ echo\ \"FAILURE\ \<-----\"$'\n' | sed -E s/^'(.*forkrun )(.*)( \| wc -l.*)$'/'\{ echo -n "forkrun \2 : "; \1\2\3; \} \| tee -a .\/forkrun.unit-tests.log'/

} > "${testPath}/forkrun.run-unit-tests.bash"



chmod +x "${testPath}/forkrun.run-unit-tests.bash"

"${testPath}/forkrun.run-unit-tests.bash" 2>/dev/null

printf '%s\n' '' 'TESTS COMPLETE!' '' 'SUMMARY:'  '' 'SUCCESSFUL: '"$(cat "${testPath}/forkrun.unit-tests.log" | grep 'SUCCESS' | wc -l)" 'FAILED '"$(cat "${testPath}/forkrun.unit-tests.log" | grep 'FAIL' | wc -l)" ''

cd "$OLDPWD"

[[ -f ./forkrun.unit-tests.log ]] && cat ./forkrun.unit-tests.log >> ./forkrun.unit-tests.log.old && rm -f ./forkrun.unit-tests.log
cp "${testPath}/forkrun.unit-tests.log" ./forkrun

