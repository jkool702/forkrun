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
        echo $'\n'seq\ 1\ ${np}\ \|\ forkrun\ {,-k\ ,-n\ }{,-l1\ }{,-j$(( $(nproc) - 1 ))\ }{,-t\ /tmp\ }{,-d\ 3\ }{,--\ }{sha1sum,sha256sum,printf\ "'"'%s\n'"'"}\ \|\ wc\ -l\ \|\ grep\ -qx\ ${np}\ \&\&\ echo\ \"PASS:\ \"\ \|\|\ echo\ \"\(\*\*\*\*\)\ FAIL:\ \ \<----------------\"$'\n'  | sed -E s/'^(.*)( \| wc -l .*echo "PASS\: )(.*echo ".*FAIL\: )(.*)$'/'sleep 0.01s \&\& \{ \1\2\1\3\1\4; \} \&'/
        echo $'\n'seq\ 1\ ${np}\ \|\ forkrun\ -i\ {,-k\ ,-n\ }{,-l1\ }{,-j$(( $(nproc) - 1 ))\ }{,-t\ /tmp\ }{,-d\ 3\ }{,--\ }{sha1sum,sha256sum,printf\ "'"'%s\n'"'"}\ \{\}\ \|\ wc\ -l\ \|\ grep\ -qx\ ${np}\ \&\&\ echo\ \"PASS:\ \"\ \|\|\ echo\ \"\(\*\*\*\*\)\ FAIL:\ \ \<----------------\"$'\n'  | sed -E s/'^(.*)( \| wc -l .*echo "PASS\: )(.*echo ".*FAIL\: )(.*)$'/'sleep 0.01s \&\& \{ \1\2\1\3\1\4; \} \&'/
done | grep -E '[^[:space:]]+' | split -l 8 --filter='cat; echo wait; echo sleep 0.2s'
} > "${testPath}/forkrun.run-unit-tests.bash"

#|\ tee\ \>\(echo\ \"value\ \=\ \$\(cat\)\"\ \>\&\2\ \)\ \

#{
#for np in $(( $(nproc) - 2 )) $(( 10 * $(nproc) + 1 )); do
#        echo $'\n'seq\ 1\ ${np}\ \|\ forkrun\ {,-k\ ,-n\ }{,-l1\ }{,-j$(( $(nproc) - 1 ))\ }{,-t\ /tmp\ }{,-d\ 3\ }{,--\ }{sha1sum,sha256sum,echo,printf\ "'"'%s\n'"'"}\ \|\ wc\ -l\ \|\ grep\ -qx\ ${np}\ \&\&\ echo\ \"PASS\"\ \|\|\ echo\ \"FAIL\ \<-----\"$'\n' | sed -E s/^'(.*)( \| wc -l.*)$'/'\{ echo -n "\1 : "; \1\2; \} \| tee -a .\/forkrun.unit-tests.log'/ 
#    echo $'\n'seq\ 1\ ${np}\ \|\ forkrun\ -i\ {,-k\ ,-n\ }{,-l1\ }{,-j$(( $(nproc) - 1 ))\ }{,-t\ /tmp\ }{,-d\ 3\ }{,--\ }{sha1sum,sha256sum,echo,printf\ "'"'%s\n'"'"}\ \{\}\ \|\ wc\ -l\ \|\ grep\ -qx\ ${np}\ \&\&\ echo\ \"PASS\"\ \|\|\ echo\ \"FAIL\ \<-----\"$'\n' | sed -E s/^'(.*)( \| wc -l.*)$'/'\{ echo -n "\1 : "; \1\2; \} \| tee -a .\/forkrun.unit-tests.log'/
#done | grep -E '[^[:space:]]+'
#} > "${testPath}/forkrun.all-unit-tests-nofork.bash"


chmod +x "${testPath}/forkrun.run-unit-tests.bash"

"${testPath}/forkrun.run-unit-tests.bash" 2>/dev/null | tee -a "${testPath}/forkrun.unit-tests.log"

#echo "retrying failed tests without forking" >&2

#cat "${testPath}/forkrun.unit-tests.log" | grep FAIL |  sed -E s/'^.*FAIL\: '// | sed -E s/' <\-*$'// | while read -r tt; do cat "${testPath}/forkrun.run-unit-tests.bash"| grep -F "$tt"; done | sed -E s/' \&$'// > "${testPath}/forkrun.run-unit-tests-nofork.bash"

#echo "$(cat "${testPath}/forkrun.unit-tests.log" | grep -v FAIL)" > "${testPath}/forkrun.unit-tests.log"

#chmod +x "${testPath}/forkrun.run-unit-tests-nofork.bash"

#"${testPath}/forkrun.run-unit-tests-nofork.bash" 2>/dev/null | tee -a "${testPath}/forkrun.unit-tests.log"

printf '%s\n' '' 'TESTS COMPLETE!' '' 'SUMMARY:'  '' 'PASSED: '"$(cat "${testPath}/forkrun.unit-tests.log" | grep 'PASS' | wc -l)" 'FAILED '"$(cat "${testPath}/forkrun.unit-tests.log" | grep 'FAIL' | wc -l)" ''

cd "$OLDPWD"

[[ -f ./forkrun.unit-tests.log ]] && cat ./forkrun.unit-tests.log >> ./forkrun.unit-tests.log.old && rm -f ./forkrun.unit-tests.log
cp "${testPath}/forkrun.unit-tests.log" ./

