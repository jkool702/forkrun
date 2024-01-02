
############################################## BEGIN CODE ##############################################

SECONDS=0
shopt -s extglob

renice --priority -20 --pid $$

declare -F forkrun 1>/dev/null 2>&1 || { 
    [[ -f ./forkrun.bash ]] || wget  https://raw.githubusercontent.com/jkool702/forkrun/forkrun-testing/forkrun.bash
    . ./forkrun.bash
}

findDirDefault='/usr'

[[ -n "$1" ]] && [[ -d "$1" ]] && findDir="$1"
: ${findDir:="${findDirDefault}"} ${ramdiskTransferFlag:=true}

findDir="$(realpath "${findDir}")"
findDir="${findDir%/}"

if ${ramdiskTransferFlag}; then

    grep -qF 'tmpfs /mnt/ramdisk' </proc/mounts || {
        printf '\nMOUNTING RAMDISK AT /mnt/ramdisk\n' >&2
        mkdir -p /mnt/ramdisk
        sudo mount -t tmpfs tmpfs /mnt/ramdisk
        sudo chown -R "$USER": /mnt/ramdisk
    }
    
    printf '\nCOPYING FILES FROM %s TO RAMDISK AT %s\n' "${findDir}" "/mnt/ramdisk/${findDir#/}" >&2
    mkdir -p "/mnt/ramdisk/${findDir}"
    rsync -a "${findDir}"/* "/mnt/ramdisk/${findDir#/}"
    \rm  -rf ./usr/lib64/dri
    
    findDir="/mnt/ramdisk/${findDir#/}"
    hfdir='/mnt/ramdisk/hyperfine'

else

  hfdir="${PWD}/hyperfine"

fi

"${testParallelFlag:=true}"

mkdir -p "${hfdir}"/{results,file_lists}

for kk in {1..6}; do
    find "${findDir}" -type f | head -n $(( 10 ** $kk )) >"${hfdir}"/file_lists/f${kk}
done

for kk in {1..6}; do 
     printf '\n-------------------------------- %s values --------------------------------\n\n' $(wc -l <"${hfdir}"/file_lists/f${kk}); 

     for c in  sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3"; do 
         printf '\n---------------- %s ----------------\n\n' "$c"; 

         hyperfine -w 1 -i --shell /usr/bin/bash --parameter-list cmd 'source '"${PWD}"'/forkrun.bash && forkrun --','xargs -P '"$(nproc)"' -d $'"'"'\n'"'"' --' --export-json ""${hfdir}"/results/forkrun.${c// /_}.f${kk}.hyperfine.results" --style=full --setup 'shopt -s extglob' --prepare 'renice --priority -20 --pid $$' '{cmd} '"${c}"' <'"${hfdir}"'/file_lists/f'"${kk}" 

     done
done