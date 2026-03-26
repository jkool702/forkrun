#!/bin/bash

source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)

# copy /usr to ramdisk
mkdir -p /mnt/forkrun_speedtest
[[ -d /mnt/forkrun_speedtest/usr_copy ]] || {

mount -t tmpfs tmpfs /mnt/forkrun_speedtest
mkdir -p /mnt/forkrun_speedtest/usr_copy
rsync -a /usr/* /mnt/forkrun_speedtest/usr_copy
}

# define some test scripts and functions
# note: xargs will not work with test shell functions....its executioon time will show as just above 0.
cat<<'EOF' > /mnt/forkrun_speedtest/test1.sh
echo $(( $(wc -c <<<"${*}") + $(wc -l <<<"${*}") ))
EOF

cat<<'EOF' > /mnt/forkrun_speedtest/test2.sh
printf '%s\n' "${@}" | LC_ALL=C sort
EOF

chmod +x /mnt/forkrun_speedtest/test{1,2}.sh

test1() {
    echo $(( $(wc -c <<<"${*}") + $(wc -l <<<"${*}") ))
}


test2() {
    printf '%s\n' "${@}" | LC_ALL=C sort
}

declare -a funcs
funcs=(sha1sum sha256sum sha512sum md5sum test1 test2 '/mnt/forkrun_speedtest/test1.sh' '/mnt/forkrun_speedtest/test2.sh')

results=''
results1=''


printf '\nTIME SPENT ON GENERATING FILELIST:\n' >&2

# my /usr has ~430k files
time { find /mnt/forkrun_speedtest/usr_copy -type f | wc -l; }

printf '\nTESTING MANY LINES PER FUNCTION CALL\n' >&2

# test forkrun vs xargs vs parallel for "many lines at a time" case
for ff in "${funcs[@]}"; do

    printf '%s\n' '---------------------------------------------' >&2
    printf '\nTESTING %s\n' "${ff}"  >&2

    printf '\n%s' 'FORKRUN: ' >&2
    results="$(printf '%s\n\n' "${results}"; printf '%s ' 'FORKRUN ('"${ff}"'): ' $'\t'; printf '%s %s\t' $({ time { find /mnt/forkrun_speedtest/usr_copy -type f | forkrun -- "${ff}" 2>/dev/null | wc -l >/dev/null; }; } 2>&1; ))"

    printf 'done\n%s' 'XARGS: ' >&2
    results="$(printf '%s\n' "${results}"; printf '%s ' 'XARGS ('"${ff}"'):   ' $'\t'; printf '%s %s\t' $({ time { find /mnt/forkrun_speedtest/usr_copy -type f | xargs -P $(nproc) -d $'\n' -- "${ff}" 2>/dev/null | wc -l >/dev/null; }; } 2>&1; ))"

    printf 'done\n%s' 'PARALLEL: ' >&2
    results="$(printf '%s\n' "${results}"; printf '%s ' 'PARALLEL ('"${ff}"'):' $'\t'; printf '%s %s\t' $({ time { find /mnt/forkrun_speedtest/usr_copy -type f | parallel -m "${ff}" 2>/dev/null | wc -l >/dev/null; }; } 2>&1; ))"

    printf 'done\n\n' >&2

    echo "${results}" | tail -n 3

    results1="$(printf '%s\n' "${results1}" '')"

done

{
    printf '\nTESTING MANY LINES PER FUNCTION CALL\n'
    printf '%s\n' "${results}" 
    printf '%s\n' '---------------------------------------------'
} | tee >(cat >>/mnt/forkrun_speedtest/results)


printf '\nTESTING 1 LINE PER FUNCTION CALL (1st 10000 lines only)\n' >&2

# test forkrun vs xargs vs parallel for "one line at a time" case
for ff in "${funcs[@]}"; do

    printf '%s\n' '---------------------------------------------' >&2
    printf '\nTESTING %s\n' "${ff}"  >&2

    printf '\n%s' 'FORKRUN-1: ' >&2
    results1="$(printf '%s\n\n' "${results1}"; printf '%s ' 'FORKRUN-1 ('"${ff}"'): ' $'\t'; printf '%s %s\t' $({ time { find /mnt/forkrun_speedtest/usr_copy -type f | head -n 10000 | forkrun -l 1 -- "${ff}" 2>/dev/null | wc -l >/dev/null; }; } 2>&1; ))"

    printf 'done\n%s' 'XARGS-1: ' >&2
    results1="$(printf '%s\n' "${results1}"; printf '%s ' 'XARGS-1 ('"${ff}"'):   ' $'\t'; printf '%s %s\t' $({ time { find /mnt/forkrun_speedtest/usr_copy -type f | head -n 10000 | xargs -P $(nproc) -d $'\n' -l -- "${ff}" 2>/dev/null | wc -l >/dev/null; }; } 2>&1; ))"

    printf 'done\n%s' 'PARALLEL-1: ' >&2
    results1="$(printf '%s\n' "${results1}"; printf '%s ' 'PARALLEL-1 ('"${ff}"'):' $'\t'; printf '%s %s\t' $({ time { find /mnt/forkrun_speedtest/usr_copy -type f | head -n 10000 | parallel "${ff}" 2>/dev/null | wc -l >/dev/null; }; } 2>&1; ))"

    printf 'done\n\n' >&2

    echo "${results1}" | tail -n 3

    results1="$(printf '%s\n' "${results1}" '')"
done


{
printf '\nTESTING 1 LINE PER FUNCTION CALL (1st 10000 lines only)\n'
printf '%s\n' "${results1}"
printf '%s\n' '---------------------------------------------' >&2
} | tee >(cat >>/mnt/forkrun_speedtest/results)
