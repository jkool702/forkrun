#!/usr/bin/env bash 

unset forkrun
declare -F forkrun &>/dev/null || source <(curl https://raw.githubusercontent.com/jkool702/forkrun/forkrun-v2_RC/forkrun.bash)
declare -F forkrun &>/dev/null || source ./forkrun.bash

mkdir -p /mnt/ramdisk
cat /proc/mounts | grep -F '/mnt/ramdisk' || mount -t tmpfs tmpfs /mnt/ramdisk

rsync -a /usr /mnt/ramdisk
which nproc 1>/dev/null 2>/dev/null && nProcs=$(nproc) || nProcs=8

mapfile -t A0 < <(find /mnt/ramdisk -type f | head -n $(( ${nProcs} * 1024 )))
mapfile -t A1 < <(printf '%s\n' "${A0[@]}" | head -n $(( ${nProcs} * 128 )))
mapfile -t A2 < <(printf '%s\n' "${A1[@]}" | head -n  $(( ${nProcs} + 2 )))
mapfile -t A3 < <(printf '%s\n' "${A2[@]}" | head -n  $(( ${nProcs} - 2 )))



for nn in A3 A2 A1 A0; do
declare -n C="$nn"

unset forkrun
declare -F forkrun &>/dev/null || source <(curl https://raw.githubusercontent.com/jkool702/forkrun/forkrun-v2_RC/forkrun.bash)
declare -F forkrun &>/dev/null || source ./forkrun.bash

echo "BEGINNING TEST CASE FOR STDIN LENGTH = ${#C[@]}"


( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -D -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -D -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -t /tmp -D -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -D -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -D -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -l 1 -t /tmp -D -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -D -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -D -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -t /tmp -D -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -D -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -- sha1sum | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -- sha1sum | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -- sha256sum | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -- sha256sum | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -- printf '%s\n') <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -- printf '"'"'%s\n'"'"''; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i -- sha1sum {} | sed -E s/'^[0-9a-f]{40}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i -- sha1sum {} | sed -E s/'"'"'^[0-9a-f]{40}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i -- sha256sum {} | sed -E s/'^[0-9a-f]{64}[ \t]*'//) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i -- sha256sum {} | sed -E s/'"'"'^[0-9a-f]{64}[ \t]*'"'"'//'; }  | tee -a /tmp/.forkrun.log; )

( { diff 2>/dev/null -q -B -E -Z -d -a -b -w <(printf '%s\n' "${C[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i -- printf '%s\n' {}) <(printf '%s\n' "${C[@]}") && printf '%s' "PASS" || printf '%s' "FAIL"; printf ': %s\n' 'printf '"'"'%s\n'"'"' "${'"${nn}"'[@]}" | forkrun 2>/dev/null -k -j 27 -l 1 -t /tmp -D -i -- printf '"'"'%s\n'"'"' {}'; }  | tee -a /tmp/.forkrun.log; )


done
