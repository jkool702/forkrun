. <( { echoFlag=false; while true; do IFS= read -r line; [[ "$line" == *'_forkrun_file_to_base64() {'* ]] && echoFlag=true; $echoFlag && echo "$line"; $echoFlag && [[ "$line" == '}'* ]] && break; done; } <frun.bash )

( 
unset b64
declare -A b64
for nn in ./**/*.so; do
mm="${nn#*forkrun_ring.}"
mm="${mm%.so}"
mm="${mm//-/_}"
b64[$mm]="$(_forkrun_file_to_base64 "$nn")"
done
{          
while IFS= read -r line; do
echo "$line"
[[ "$line" == *'# <@@@@@< _BASE64_START_ >@@@@@> #'* ]] && break
done
echo 
declare -p b64
printf '\n%s\n' '_forkrun_bootstrap_setup --force'
} <frun.bash >frun.new.bash 
)

