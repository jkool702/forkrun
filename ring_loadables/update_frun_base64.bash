
update_frun_base64() (

if [[ "$1" ]] && [[ -f "$1" ]]; then
    frun_path="$1"
else
    frun_path="./frun.bash"
fi

[[ -f "$frun_path" ]] || return 1

. <( { echoFlag=false; while true; do IFS= read -r line; [[ "$line" == *'_forkrun_file_to_base64() {'* ]] && echoFlag=true; $echoFlag && echo "$line"; $echoFlag && [[ "$line" == '}'* ]] && break; done; } <"${frun_path}" )

( 
unset b64
declare -A b64
shopt -s globstar
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
} <"${frun_path}" >"${frun_path%.bash}.new.bash"

[[ -s "${frun_path%.bash}.new.bash" ]] && command mv -f "${frun_path%.bash}.new.bash" "${frun_path}"

)

)
