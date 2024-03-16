#!/usr/bin/env bash
# shellcheck disable=SC2004,SC2059,SC2317 source=/dev/null

shopt -s extglob

dupefind() { (
    ## Quickly finds duplicate files using "forkrun", "du", and the "sha1sum" hash
    #
    # USAGE: dupefind [-q] [-e] <path> [<path2> ...] [\!<epath> \!<epath2 ...]
    #
    #  all <path> locations are recursively searched under (at any depth level) for duplicates
    #  all <epath> locations (and anything under at any depth level) are excluded from the search
    #
    # EXAMPLE: dupefind -e / \!/{root,efi,DATA}
    #
    # For more detailed help, run `dupefind -h`

_dupefind_help() ( cat<<'EOF' >&2
## dupefind: quickly finds duplicate files using "forkrun", "du", and the "sha1sum" hash
#
# dupefind implements a 2 stage search for duplicate files:
#    it first finds files that have identical sizes (unless the '-s' flag is passed), then
#    for these files, it computes the sha1sum hash and looks for matching hashes
#
# USAGE: dupefind [-q] [-e] <path> [<path2> ...] [\!<epath> \!<epath2 ...]
#
# EXAMPLE: dupefind -e / \!/{root,efi,DATA}
#
# INPUTS: 
#     all <path> locations are recursively searched under (at any depth level) for duplicates
#     all <epath> (inputs with a leading `!`) locations (and under) are excluded from the search
#         NOTE: dont forget to quote/escape the '!': use '!/path' or \!/path
#
#      NOTES: If you want to look for duplicates under a directory starting with a '!' or '-h'
#                 then use the full path (e.g. use '/${PWD}/!whyyyy', not '!whyyyy')
#             Default when no inputs are passed:   dupefind -e /
#
# FLAGS:
#     to prevent printing informational info to stderr, pass flag '-q' or '--quiet'
#     to automatically exclude '/dev' '/proc' '/run' '/sys' '/tmp', pass flag '-e' or '--exclude'
#     to display this help, pass flag '-h' or '-?' or '--help'
#
# OUTPUT: 
#    stdout contains a newline-separated list of duplicate files,
#    each group of duplicates is separated by a blank line *and* a NULL
#    when both a) output is to a terminal, and b) the '-q' flag is not used, then:
#        a separator line, the sha1sum hash, and the file size (unless '-s') of each duplicate set are also printed
#
# DEPENDENCIES: forkrun, find,, sha1sum        
EOF
)

    set +C
    shopt -s extglob

    # source forkrun
    declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source ./forkrun.bash; } || { type -p forkrun.bash &>/dev/null && source "$(type -p forkrun.bash )"; } || source <(curl 'https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash') || { printf '\nERROR!!! The forkrun function is not defined and its source code could not be found/downloaded. ABORTING!\n\n'; return 1; }

    # make vars local
    local excludeStr dfTmpDirRoot dfTmpDir nn nnCur sizeCutoff quietFlag autoExcludeFlag 
    local -a searchA excludeA searchA0 excludeA0 fd_numFilesA
    local -i kk

    #PID0=$$



    # parse inputs
    :  "${quietFlag:=false}" "${autoExcludeFlag:=false}" "${sizeCutoff:=$(( 2 ** 20 ))}"
    if [[ $# == 0 ]]; then
        # set default runtime values
        searchA=('/')
        excludeA=('/dev' '/proc' '/run' '/sys' '/tmp')
    else
        # loop over inputs
        for nn in "$@"; do
            case "${nn}" in
                -h|-\?|--help) _dupefind_help; return 0 ;;
                -q|-quiet) quietFlag=true ;;
                -e|--exclude) autoExcludeFlag=true ;;
                --cutoff=*) sizeCutoff="${nn##*=}" ;;
                '!'*) excludeA+=("${nn#'!'}") ;;
                *) searchA+=("${nn}") ;;
            esac
        done

        [[ ${#searchA[@]} == 0 ]] && searchA=('/')

        # if doing a full system search 'everything under /' and not using -q flag check if they want to skip '/dev' '/proc' '/sys' '/tmp'
        if [[ "${searchA[*]}" == '/' ]] && { ${autoExcludeFlag} || ! ${quietFlag}; }; then
            for nnCur in '/dev' '/proc' '/run' '/sys' '/tmp'; do
                ( IFS=' '; [[ " ${excludeA[*]} " == *' '"${nnCur}"?(/)' '* ]] ) || {
                    { ${autoExcludeFlag} || { read -r -p "would you like to exclude ${nnCur} from your search for duplicate files? "$'\n'"(Y/n)  " -t 10 -n 1; ! [[ "${REPLY}" == [nN] ]]; }; } && excludeA+=("${nnCur}")
                }
            done
        fi
    fi

    # setup tmpdir for dupefind
    [[ ${dfTmpDirRoot} ]] || { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && dfTmpDirRoot="${TMPDIR}"; } || { [[ -d '/dev/shm' ]] && dfTmpDirRoot='/dev/shm'; }  || { [[ -d '/tmp' ]] && dfTmpDirRoot='/tmp'; } || dfTmpDirRoot="$(pwd)"
    dfTmpDir="$(mktemp -p "${dfTmpDirRoot}" -d .dupefind.XXXXXX)"

    # add tmpDir to exclude list, then remove unnecessary duplicates in search and exclude lists
    # e.g., if it includes '/dev' and '/dev/shm/.dupefind.XXXXXX', remove '/dev/shm/.dupefind.XXXXXX' since it is already covered by '/dev'
    excludeA+=("${dfTmpDir}")
    
    searchA0=("${searchA[@]%'/'}")
    searchA0=("${searchA0[@]%'/*'}")
    excludeA0=("${excludeA[@]%'/'}")
    excludeA0=("${excludeA0[@]%'/*'}")

    source <(printf 'searchA=("${searchA[@]%%%%"%s"/*}")\n' "${searchA0[@]}")
    source <(printf 'excludeA=("${excludeA[@]%%%%"%s"/*}")\n' "${excludeA0[@]}")

    mapfile -t -d '' searchA < <(printf '%s\0' "${searchA[@]}" | sed -z s/'^$'/'\/'/ | sort -u -z)
    mapfile -t -d '' excludeA < <(printf '%s\0' "${excludeA[@]}" | sed -z s/'^$'/'\/'/ | sort -u -z)

    # parse sizeCutoff to get byte count     
    sizeCutoff="${sizeCutoff,,}"
	sizeCutoff="${sizeCutoff//[[:space:]]/}"
	sizeCutoff="${sizeCutoff%b}"
	
	[[ "${sizeCutoff}" == +([0-9])@([kmgtp])?(i) ]] && {
		local -A sizeCutoffParser=([k]=1 [m]=2 [g]=3 [t]=4 [p]=5)

		if [[ ${sizeCutoff: -1:1} == 'i' ]]; then
			sizeCutoff="$(( ${sizeCutoff%[kmgtp]i} * ( 1024 ** ${sizeCutoffParser[${sizeCutoff: -2:1}]} ) ))"
		else
			sizeCutoff="$(( ${sizeCutoff%[kmgtp]} * ( 1000 ** ${sizeCutoffParser[${sizeCutoff: -1:1}]} ) ))"
		fi
	}

	# make sure sizeCutoff is only digits or use default of 1 MiB
	[[ "${sizeCutoff//[0-9]/}" ]] || sizeCutoff=1048576
	
	# set minimim sizeCutoff to 128 KiB
	(( ${sizeCutoff} < 131072 )) && sizeCutoff=131072


    # rm tmpdir on exit
    trap '${quietFlag} || printf '"'"'\n'"'"' >&${fd_progress}; \rm -rf "${dfTmpDir}"' EXIT INT HUP TERM

    # print info about parsed options
    ${quietFlag} || {
        printf '\n\ndupefind will now search for duplicate files under : '
        printf "'%s' " "${searchA[@]}"
        printf '\n'
        [[ ${#excludeA[@]} == 0 ]] || { 
            printf 'the following files/directories will be excluded: '
            printf "'%s' " "${excludeA[@]}"
            printf '\n'
        }
        printf 'dupefind file data will be temporairly stored under: %s\n\n' "${dfTmpDir}" 
    } >&2

    # setup find exclusions
    printf -v excludeStr ' -path '"'"'%s'"'"' -prune -o ' "${excludeA[@]}"

    # make tmp dirs for _dupefind_size
    mkdir -p "${dfTmpDir}"/size/{data,dupes} 


_dupefind_progress() (
    ## Prints progress of current operation to screen
    {
        local percentCur lineCur lineNew numFilesAdd fallocateFlag
        local -a -i numFilesAll numFilesCur numFilesFallocate

        type -p fallocate >&/dev/null && fallocateFlag=true || fallocateFlag=false
        
        shopt -s extglob

        {
            SECONDS=0
            printf '\n\n--------------------------------------------------------------------------------\nPROGRESS REPORT FOR THE FOLLOWING %s TASKS:\n\n' $# >&${fd2}

            # setup arrays for file counts
            for (( kk=1; kk<=$#; kk++ )); do
                printf 'TASK %s: %s\n' "${kk}" "${!kk}" >&${fd2}
                numFilesAll[$kk]=0
                numFilesCur[$kk]=0
                ${fallocateFlag} && numFilesFallocate[$kk]=0
            done

            lineCur=1
   
            while true; do
                # read progress update
                read -r -u ${fd_progress} lineNew numFilesAdd
                [[ ${numFilesAdd} ]] || break

                # add update to file count of specified task
                numFilesCur[${lineNew}]+=${numFilesAdd}
                [[ -f /proc/self/fdinfo/${fd_numFilesA[${lineNew}]} ]] && {
                    read -r </proc/self/fdinfo/${fd_numFilesA[${lineNew}]}
                    [[ ${REPLY##*$'\t'} == +([0-9]) ]] && numFilesAll[${lineNew}]="${REPLY##*$'\t'}"
                }

                # makew file sparse if we have fallocate
                ${fallocateFlag} && {
                    numFilesFallocate[$lineNew]+=${numFilesAdd}
                    (( numFilesFallocate[$lineNew] >= 4096 )) && fallocate -d --offset 0 --length $(( 4096 * ( ${numFilesCur[${lineNew}]} / 4096 ) )) "${dfTmpDir}/totalCur${lineNew}"
                }

                # get current percent from file counts
                (( ${numFilesAll[${lineNew}]} > 0 )) && percentCur="$(( 100 * ${numFilesCur[${lineNew}]} / ${numFilesAll[${lineNew}]} ))" || percentCur='???'

                # move curson to correct line for task update
                printf '\r' >&${fd2}
                [[ "${lineCur}" == "${lineNew}" ]] || {
                    if (( "${lineCur}" > "${lineNew}" )); then 
                        printf '\033['"$(( ${lineCur} - ${lineNew}))"'A' >&${fd2}
                    else
                        printf '\033['"$(( ${lineNew} - ${lineCur}))"'B' >&${fd2} 
                    fi
                }

                # update status line for task
                printf '\033[KTASK #%s:  %s \t / \t %s \t ( %s%% )' "${lineNew}" "${numFilesCur[${lineNew}]}" "${numFilesAll[${lineNew}]}" "${percentCur}" >&${fd2}

                lineCur="${lineNew}"
            done

            # finished. print overall time taken
            printf '\n\nFINISHED!!!\n\nTIME TAKEN: %s SECONDS\n\n' "${SECONDS}" >&${fd2}
            exec {fd2}>&-
        } &
    } {fd2}>&2

)

_dupefind_size() (
    # function run in parallel by forkrun to find duplicate files size

    set -C
    shopt -s extglob

    local -a fSizeA fNameA
    local -i kk
    local fHash0 nn mm

    # get file size/name and split into 2 arrays
    fNameA=("${@#*/}")
    fSizeA=("${@%%/*}")

    # add each file name to a file named using the file size under ${dfTmpDir}/size/data using a '>' redirect
    # If the file already exists this will fail (due to set -C), meaning it is a duplicate. in this case append ('>>') the filename instead and
    #  note that there are multiple files with this size by creating directory ${dfTmpDir}/size/dupes/<filesize> + make "<...>/link" to the data
    for kk in "${!fSizeA[@]}"; do
        { [[ ${fSizeA[$kk]} == +([0-9]) ]] && [[ -f "${fNameA[$kk]}" ]]; } || continue   

        (( ${fSizeA[$kk]} > $sizeCutoff )) && {
            fHash0="$({ dd if="${fNameA[$kk]}" bs=64k count=1 iflag=fullblock status=none; dd if="${fNameA[$kk]}" bs=64k count=1 iflag=fullblock status=none skip=$(( ${fSizeA[$kk]} - 65536 ))B; } | sha1sum)"
            printf -v 'fSizeA['"$kk"']' '%s_%s' "${fSizeA[$kk]}" "${fHash0%%*(' ')?(-)}"
        }

        if [[ -d "${dfTmpDir}/size/dupes/${fSizeA[$kk]}" ]]; then
            printf '%s\0' "${fNameA[$kk]}" >>"${dfTmpDir}/size/data/${fSizeA[$kk]}"
        else
            printf '%s\0' "${fNameA[$kk]}" >"${dfTmpDir}/size/data/${fSizeA[$kk]}" || {
                mkdir -p "${dfTmpDir}/size/dupes/${fSizeA[$kk]}"
                printf '%s\0' "${fNameA[$kk]}" >>"${dfTmpDir}/size/data/${fSizeA[$kk]}"
            }
        fi 2>/dev/null

    done

    ${quietFlag} || printf '1 %s\n' "${#fNameA[@]}" >&${fd_progress}
)

_dupefind_rmDupeLinks() (
    
    local -A fNameA 
    local -i kk
    local mm fSizeCur 

    # for each duplicate file of a given size, use find -L to list device+inode number, size and filename in [<device>_<inode>]="<size>/<name>" format
    # wrap this in fNameA=(...) to make it a bash array, which will only keep 1 listing per inode, 
    # this will remove duplicate listings for a given file (including symlinks and hardlinks to that file)
    for fSizeCur in "$@"; do
    
        [[ -f "${dfTmpDir}/size/data/${fSizeCur}" ]] && source <(printf 'fNameA=('; { source /proc/self/fd/0; } <<<"find -L -O3 -maxdepth 0 -files0-from \"${dfTmpDir}/size/data/${fSizeCur}\" ${excludeStr} -printf '[\$(( ( %i << 16 ) + %D ))]=\"${fSizeCur}/%p\" '"; printf ')')
        printf '%s\0' "${fNameA[@]}"
        
    done

    ${quietFlag} || printf '2 %s\n' "${#}" >&${fd_progress}

)

_dupefind_hash() (
    # function run in parallel by forkrun to find duplicate file sha1sum hashes

    set -C

    local -a fHashA fSizeA fNameA fNameRm
    local -A fName0
    local -i kk

    # get file size[_hash-partial]/name from name and compute hash with 'sha1sum' and split into 3 arrays
    fSizeA=("${@%%/*}")
    fNameA=("${@#*/}")
    
    mapfile -t -d '' fHashA < <(sha1sum -z "${fNameA[@]}" 2>&1)
    fHashA=("${fHashA[@]%%?(sha1sum:) *}")

    # add each file name to a file named using the file size under ${dfTmpDir}/size/dupes/<size>/hash/data using a '>' redirect
    # If the file already exists this will fail (due to set -C), meaning it is a duplicate. in this case append ('>>')
    # the filename instead and note that there are duplicate files with this hash by touching ${dfTmpDir}/size/dupes/<size>/hash/dupes/<hash>
     for kk in "${!fHashA[@]}"; do
        { [[ ${fHashA[$kk]} ]] && [[ ${fSizeA[$kk]} == +([0-9]) ]] && [[ -f "${fNameA[$kk]}" ]]; } || continue

        [[ -d "${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash" ]] || mkdir -p "${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash"/{data,dupes}

        printf '%s\n\0' "${fNameA[$kk]}" >"${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash/data/${fHashA[$kk]}" || {
            printf '%s\n\0' "${fNameA[$kk]}" >>"${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash/data/${fHashA[$kk]}"
            [[ -f "${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash/dupes/${fHashA[$kk]}" ]] || : >"${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash/dupes/${fHashA[$kk]}"
        }
    done &>/dev/null

    ${quietFlag} || printf '3 %s\n' "${#fNameA[@]}" >&${fd_progress}
)

_dupefind_print() (
    # print duplicate files found and (if outputting to a terminal) stuff to make it look nice to stdout
    local nn nnCur
    for nn in "$@"; do
        nnCur="${dfTmpDir}/size/dupes/${nn%'/hash/dupes/'*}/hash/data/${nn##*/}"
        printf '\n\0' >> "${nnCur}"
            if ${quietFlag} || ! [ -t 1 ]; then
                cat "${nnCur}"
            else
                printf '\n\n-------------------------------------------------------\nCKSUM HASH: %s\nFILE SIZE: %s\n\n' "${nn##*/}" "${nn%%/*}" 
                cat "${nnCur}"
            fi
    done

    ${quietFlag} || [ -t 1 ] || printf '4 %s\n' "${#}" >&${fd_progress}

)



        # prepare for on-screen progress indicator
        ${quietFlag} || {
            echo 0 >"${dfTmpDir}"/totalCur1
            echo 0 >"${dfTmpDir}"/totalCur2
            echo 0 >"${dfTmpDir}"/totalCur3
            echo 0 >"${dfTmpDir}"/totalCur4
            { :; } {fd_progress}<><(:) {fd_numFilesA[1]}>"${dfTmpDir}"/totalCur1 {fd_numFilesA[2]}>"${dfTmpDir}"/totalCur2 {fd_numFilesA[3]}>"${dfTmpDir}"/totalCur3 {fd_numFilesA[4]}>"${dfTmpDir}"/totalCur4

            if [ -t 1 ]; then
                _dupefind_progress 'CHECKING FILE SIZES FOR IDENTICALLY SIZED FILES' 'CHECKING FOR [LINKED] DUPLICATE FILES IN FILE LISTS' 'COMPUTING SHA1SUM HASH FOR FILES WITH IDENTICAL SIZES'
            else
                _dupefind_progress 'CHECKING FILE SIZES FOR IDENTICALLY SIZED FILES' 'CHECKING FOR [LINKED] DUPLICATE FILES IN FILE LISTS' 'COMPUTING SHA1SUM HASH FOR FILES WITH IDENTICAL SIZES' 'PRINTING DUPLICATE FILE LIST TO SPECIFIED FILE'
            fi

        }

        # search for duplicate file sizes by using forkrun to run _dupefind_size
        if ${quietFlag}; then
            { source /proc/self/fd/0 <<<"find -O3 -H \"\${searchA[@]}\" ${excludeStr} -type f -printf '%s/%p\0'"; } | forkrun -z _dupefind_size
        else
            printf '\nBeginning search for files with identical size\n' >&2;

            { source /proc/self/fd/0 <<<"find -O3 -H \"\${searchA[@]}\" ${excludeStr} -type f -printf '%s/%p\0'"; } | tee >(tr -d -c '\0' | tr '\0' '\n' >&${fd_numFilesA[1]}) | forkrun -z _dupefind_size

            exec {fd_numFilesA[1]}>&-;  
            \rm -f "${dfTmpDir}"/totalCur1; 
        fi
        
       

        # remove duplicate listings of a file (or symlinks/hardlinks to the file) and search for duplicate file hashes by using chained forkrun instances to run _dupefind_rmDupeLinks and _dupefind_hash
        if [[ $(find "${dfTmpDir}"/size/dupes -maxdepth 0 -empty) ]]; then
            # no duplicate file sizes means no duplicates. Skip computing hashes.
            ${quietFlag} || printf '\nNo files with the exact same size found. \nSkipping duplicate search based on file hash.\n' >&2
            return 0
        else
            if ${quietFlag}; then
                find "${dfTmpDir}"/size/dupes/ -mindepth 1 -maxdepth 1 -printf '%P\0' | forkrun -z _dupefind_rmDupeLinks | forkrun -z _dupefind_hash
            else
                printf '\nChecking for multiple links to the same file and beginning search for files with identical sha1sum hash\n' >&2;
             
                find "${dfTmpDir}"/size/dupes/ -mindepth 1 -maxdepth 1 -printf '%P\0' | tee >(tr -d -c '\0' | tr '\0' '\n' >&${fd_numFilesA[2]}) | forkrun -z -k _dupefind_rmDupeLinks | tee >(tr -d -c '\0' | tr '\0' '\n' >&${fd_numFilesA[3]}) | forkrun -z _dupefind_hash

                exec {fd_numFilesA[2]}>&- {fd_numFilesA[3]}>&-;  
                \rm -f "${dfTmpDir}"/totalCur2 "${dfTmpDir}"/totalCur3;
            fi
        fi
        

        # group and print duplicate files found by using forkrun to run _dupefind_size
        if [[ $(find "${dfTmpDir}"/size/dupes/ -mindepth 4 -maxdepth 4 -path "${dfTmpDir}"'/size/dupes/*/hash/dupes/*' -type f) ]]; then

            if ${quietFlag}; then 
                find "${dfTmpDir}"/size/dupes/ -mindepth 4 -maxdepth 4 -path "${dfTmpDir}"'/size/dupes/*/hash/dupes/*' -type f -printf '%P\0' | forkrun -z -k _dupefind_print
            else
                [ -t 1 ] || printf '\nPrinting duplicate file list to specified output file\n' >&2
                find "${dfTmpDir}"/size/dupes/ -mindepth 4 -maxdepth 4 -path "${dfTmpDir}"'/size/dupes/*/hash/dupes/*' -type f -printf '%P\0' | tee >(tr -d -c '\0' | tr '\0' '\n' >&${fd_numFilesA[4]}) | forkrun -z -k _dupefind_print 
           
                exec {fd_numFilesA[4]}>&-
                \rm -f "${dfTmpDir}"/totalCur4
                printf '\n' >&${fd_progress}
            fi
        else
            ${quietFlag} || printf '\nNO DUPLICATES FOUND\n' >&2
            return 0
       fi
  ) 
}
