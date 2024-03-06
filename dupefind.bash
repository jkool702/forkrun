#!/usr/bin/env bash


dupefind() { (
    ## Quickly finds duplicate files using "forkrun", "du", and the "sha1sum" hash
    #
    # USAGE: dupefind [-q] [-e] [-s] <path> [<path2> ...] [\!<epath> \!<epath2 ...]
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
# USAGE: dupefind [-q] [-e] [-s] <path> [<path2> ...] [\!<epath> \!<epath2 ...]
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
#     to skip the initial search for files with identical size, pass flag '-s' or '--sha1' or '--sha1sum' or '--sha1-only' or '--sha1sum-only'
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
# DEPENDENCIES: forkrun, find, du*, sha1sum        *not required with -c flag
EOF
)

    set +C
    shopt -s extglob

    # source forkrun
    declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source ./forkrun.bash; } || { type -p forkrun.bash &>/dev/null && source "$(type -p forkrun.bash )"; } || source <(curl 'https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash') || { printf '\nERROR!!! The forkrun function is not defined and its source code could not be found/downloaded. ABORTING!\n\n'; return 1; }

    # make vars local
    local excludeStr dfTmpDirRoot dfTmpDir nn nnCur sizeCutoff 
    local -a searchA excludeA useSizeFlag quietFlag autoExcludeFlag 

    #PID0=$$


    sizeCutoff=$(( 2 ** 20 ))

    # parse inputs
    : "${useSizeFlag:=true}" "${quietFlag:=false}" "${autoExcludeFlag:=false}"
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
                -s|--sha1|--sha1sum|--sha1-only|--sha1sum-only) useSizeFlag=false ;;
                '!'*) excludeA+=("${nn#'!'}") ;;
                *) searchA+=("${nn}") ;;
            esac
        done

        [[ ${#searchA[@]} == 0 ]] && searchA=('/')

        # if doing a full system search 'everything under /' and not using -q flag check if they want to skip '/dev' '/proc' '/sys' '/tmp'
        if [[ "${searchA[*]}" == '/' ]] && { ${autoExcludeFlag} || ! ${quietFlag}; }; then
            for nnCur in '/dev' '/proc' '/run' '/sys' '/tmp'; do
                ( IFS=' '; [[ " ${excludeA[*]} " == *' '"${nnCur}"?(/)' '* ]] ) || {
                    { ${autoExcludeFlag} || { read -p "would you like to exclude ${nnCur} from your search for duplicate files? "$'\n'"(Y/n)  " -t 10 -n 1; ! [[ "${REPLY}" == [nN] ]]; }; } && excludeA+=("${nnCur}")
                }
            done
        fi
    fi

    # setup tmpdir for dupefind
    [[ ${dfTmpDirRoot} ]] || { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && dfTmpDirRoot="${TMPDIR}"; } || { [[ -d '/dev/shm' ]] && dfTmpDirRoot='/dev/shm'; }  || { [[ -d '/tmp' ]] && dfTmpDirRoot='/tmp'; } || dfTmpDirRoot="$(pwd)"
    dfTmpDir="$(mktemp -p "${dfTmpDirRoot}" -d .dupefind.XXXXXX)"
    excludeA+=("${dfTmpDir}")

    # rm tmpdir on exit
    trap 'printf '"'"'\n'"'"' >&${fd_progress}; \rm -rf "${dfTmpDir}"' EXIT INT HUP TERM

    ${quietFlag} || {
        printf '\n\ndupefind will now search for duplicate files under : '
        printf "'%s' " "${searchA[@]}"
        printf '\n'
        [[ ${#excludeA[@]} == 0 ]] || { 
            printf 'the following files/directories will be excluded: '
            printf "'%s' " "${excludeA[@]}"
        }
        printf '\ndupefind file data will be temporairly stored under: %s\n\n' "${dfTmpDir}" 
    } >&2

    # setup find exclusions
    printf -v excludeStr ' -path '"'"'%s'"'"' -prune -o ' "${excludeA[@]}"


    if ${useSizeFlag}; then
        # search for duplicate file sizes

        # make tmp dirs for _dupefind_size
        mkdir -p "${dfTmpDir}"/size/{data,dupes} 


_dupefind_progress() { 
    {
        # Prints progress of current operation to screen
        local percentCur lineCur lineNew numFilesAdd
        local -a -i fd_numFilesA numFilesAll numFilesCur 

        shopt -s extglob

        [[ ${REPLY##*$'\t'} == +([0-9]) ]] && numFilesAll="${numFilesAll##*$'\t'}" || numFilesAll=0

        {
            SECONDS=0
            printf '\n\n--------------------------------------------------------------------------------\nPROGRESS REPORT FOR THE FOLLOWING %s TASKS:\n\n' $#

            for (( kk=0; kk<$#; kk++ )); do
                printf 'TASK %s: %s\n' "${kk}" "${!kk}"
                source /proc/self/fd/0 <<<"fd_numFilesA[${kk}]=(\"\${fd_numFiles${kk}}\")"
                numFilesAll[$kk]=0
                numFilesCur[$kk]=0
            done

            lineCur=0
   
            while true; do
                read -r -u ${fd_progress} lineNew numFilesAdd
                [[ ${numFilesAdd} ]] || break

                numFilesCur[${lineNew}]+=${numFilesAdd}
                [[ -f /proc/self/fdinfo/${fd_numFilesA[${lineCur}]} ]] && {
                    read -r </proc/self/fdinfo/${fd_numFilesA[${lineCur}]}
                    [[ ${REPLY##*$'\t'} == +([0-9]) ]] && numFilesAll[${lineNew}]="${REPLY##*$'\t'}"
                }

                (( ${numFilesAll[${lineNew}]} > 0 )) && percentCur="$(( 100 * ${numFilesCur} / ${numFilesAll} ))" || percentCur='???'

                [[ "${lineCur}" == "${lineNew}" ]] || {
                    if (( "${lineCur}" > "${lineNew}" )); then 
                        printf '\033['"$(( ${lineCur} - ${lineNew}))"'A'
                    else
                        printf '\033['"$(( ${lineNew} - ${lineCur}))"'B'
                    fi
                }
                printf '\033[K\rTASK #%s:  %*s%s\t/\t%*s%s\t( %s%% )' "${lineNew}" 8 "${numFilesCur[${lineNew}]}" 8 "${numFilesNew[${lineNew}]}" "${percentCur}"

                lineCur="${lineNew}"
            done
            printf '\n\nFINISHED!!!\n\nTIME TAKEN: %s SECONDS\n\n' "${SECONDS}" >&${fd2}
            exec {fd2}>&-
        } &
    } {fd2}>&2
    
}

_dupefind_size() (
    # function run in parallel by forkrun to find duplicate files size

    set -C
#    set -v
    shopt -s extglob
#    IFS=$'\n'

    local -a fSizeA fNameA
    local -i kk
    local fHash0 nn mm

    # get file size/name and split into 2 arrays
    fNameA=("${fSizeA[@]#*/}")
    fSizeA=("${fSizeA[@]%%/*}")

    # add each file name to a file named using the file size under ${dfTmpDir}/size/data using a '>' redirect
    # If the file already exists this will fail (due to set -C), meaning it is a duplicate. in this case append ('>>') the filename instead and
    #  note that there are multiple files with this size by creating directory ${dfTmpDir}/size/dupes/<filesize> + make "<...>/link" to the data
    for kk in "${!fSizeA[@]}"; do
        [[ ${fSizeA[$kk]} == +([0-9]) ]] || continue   

        (( ${fSizeA[$kk]} > $sizeCutoff )) && {
            fHash0="$({ dd if="${fNameA[$kk]}" bs=64k count=1 iflag=fullblock status=none; dd if="${fNameA[$kk]}" bs=64k count=1 iflag=fullblock status=none skip=$(( ${fSizeA[$kk]} - 65536 ))B; } | sha1sum)"
            printf -v 'fSizeA['"$kk"']' '%s_%s' "${fSizeA[$kk]}" "${fHash0% -}"
        }

        if [[ -d "${dfTmpDir}/size/dupes/${fSizeA[$kk]}" ]]; then
            printf '%s/root/%s\0' "${fSizeA[$kk]}" "${fNameA[$kk]}" >>"${dfTmpDir}/size/data/${fSizeA[$kk]}"
        else
            printf '%s/root/%s\0' "${fSizeA[$kk]}" "${fNameA[$kk]}" >"${dfTmpDir}/size/data/${fSizeA[$kk]}" || {

                mkdir -p "${dfTmpDir}/size/dupes/${fSizeA[$kk]}"
                ln -sf "${dfTmpDir}/size/data/${fSizeA[$kk]}" "${dfTmpDir}/size/dupes/${fSizeA[$kk]}/link"
                ln -sf / "${dfTmpDir}/size/dupes/${fSizeA[$kk]}/root"

               printf '%s/root/%s\0' "${fSizeA[$kk]}" "${fNameA[$kk]}" >>"${dfTmpDir}/size/data/${fSizeA[$kk]}"
            }
        fi 2>/dev/null

    done

    ${quietFlag} || printf '0 %s\n' "${#fNameA[@]}" >&${fd_progress}
)

_dupefind_rmDupeLinks() {
    
    local -a fNameA fSizeA fNameRm
    local -A fName0
    local -i kk
    local mm fNameCur fSizeCur

    pushd "${dfTmpDir}"/size/dupes

    # print all non-duplicate-{hard,soft}links sop their sha1sum can start to be computed
    for fSizeCur in "$@"; do
        find -L -O3 -files0-from "${dfTmpDir}"/size/data/"${fSizeCur}" -maxdepth 0 -links 1 -print0
    done

    for fSizeCur in "$@"; do
        mapfile -t -d '' fNameA < <(find -L -O3 -files0-from "${dfTmpDir}"/size/data/"${fSizeCur}" -maxdepth 0 -links +1 -print0)
        [[ ${#fNameA[@]} == 0 ]] && continue
        for kk in "${!fNameA[@]}"; do
            fName0["${fNameA[${kk}]}"]="${kk}"
        done
        for kk in "${!fNameA[@]}"; do
            [[ ${fNameA[$kk]} ]] || continue
            fNameCur="${fNameA[$kk]}"
            unset "fNameA[$kk]"
            mapfile -t -d '' fNameRm < <(find -L "${fNameA[@]}" -samefile "${fNameCur}" -print0)
            for mm in "${fNameRm[@]}"; do
                unset "fNameA[${fName0["${mm}"]}]"
            done
            { [[ ${kk} == 0 ]] && [[ ${#fNameA[@]} == 1 ]]; } || printf '%s\0' "${fNameCur}"
        done
    done
    
    ${quietFlag} || printf '1 %s\n' "${#}" >&${fd_progress}

    popd
}

_dupefind_hash() (
    # function run in parallel by forkrun to find duplicate file sha1sum hashes

    set -C
#    set -v
#    IFS=$'\n'

    local -a fHashA fSizeA fNameA fNameRm
    local -A fName0
    local -i kk

    # get file size[_hash-partial]/name from name and compute hash with 'sha1sum' and split into 3 arrays
    fSizeA=("${@%%/*}")
    fNameA=("${@#*/root}")
    
    mapfile -t -d '' fHashA < <(sha1sum -z "${fNameA[@]}" 2>&1)
    fHashA=("${fHashA[@]%%?(sha1sum:) *}")

    #${realpathFlag} && mapfile -t -d '' fNameA < <(realpath -z "${fNameA[@]}")

    # add each file name to a file named using the file size under ${dfTmpDir}/size/dupes/<size>/hash/data using a '>' redirect
    # If the file already exists this will fail (due to set -C), meaning it is a duplicate. in this case append ('>>')
    # the filename instead and note that there are duplicate files with this hash by touching ${dfTmpDir}/size/dupes/<size>/hash/dupes/<hash>
     for kk in "${!fHashA[@]}"; do
        [[ -z ${fHashA[$kk]} ]] && continue

        [[ -d "${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash" ]] || mkdir -p "${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash"/{data,dupes}

        printf '%s\n\0' "${fNameA[$kk]}" >"${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash/data/${fHashA[$kk]}" || {
            printf '%s\n\0' "${fNameA[$kk]}" >>"${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash/data/${fHashA[$kk]}"
            [[ -f "${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash/dupes/${fHashA[$kk]}" ]] || : >"${dfTmpDir}/size/dupes/${fSizeA[$kk]}/hash/dupes/${fHashA[$kk]}"
        }
    done &>/dev/null

    ${quietFlag} || printf '2 %s\n' "${#fNameA[@]}" >&${fd_progress}
)

_dupefind_print() (
    # print duplicate files found and (if outputting to a terminal) stuff to make it look nice to stdout
    local nn nnCur
    for nn in "$@"; do
        nnCur="${nn%'/hash/dupes/'*}/hash/data/${nn##*/}"
        printf '\n\0' >> "${nnCur}"
            if ${quietFlag} || ! [ -t 1 ]; then
                cat "${nnCur}"
            else
                nnSize="${nn##"${dfTmpDir}/size/dupes/"}"
                printf '\n\n-------------------------------------------------------\nCKSUM HASH: %s\nFILE SIZE: %s\n\n' "${nn##*/}" "${nnSize%%/*}" 
                cat "${nnCur}"
            fi
    done

    ${quietFlag} || printf '4 %s\n' "${#}" >&${fd_progress}

)



        # search for duplicate file sizes by using forkrun to run _dupefind_size
       
        ${quietFlag} || {
            : >"${dfTmpDir}"/totalCur{0,1,2,3}; 
            exec {fd_numFiles0}>"${dfTmpDir}"/totalCur0 {fd_numFiles1}>"${dfTmpDir}"/totalCur1 {fd_numFiles2}>"${dfTmpDir}"/totalCur2 {fd_numFiles3}>"${dfTmpDir}"/totalCur3 {fd_progress}<><(:); 
            _dupefind_progress 'CHECKING FILE SIZES FOR IDENTICALLY SIZED FILES' 'CHECKING FOR [LINKED] DUPLICATE FILES IN FILE LISTS' 'COMPUTING SHA1SUM HASH FOR FILES WITH IDENTICAL SIZES' $([ -t 1 ] || echo 'PRINTING DUPLICATE FILE LIST TO THE TERMINAL'); 
        }

        if ${quietFlag}; then
            { source /proc/self/fd/0 <<<"find -L -O3 \"\${searchA[@]}\" ${excludeStr} -type f -printf '%b/%p\0'"; } | forkrun -z -k _dupefind_size
        else
            printf '\nBeginning search for files with identical size\n' >&2;

            { source /proc/self/fd/0 <<<"find -L -O3 \"\${searchA[@]}\" ${excludeStr} -type f -printf '%b/%p\0'"; } | tee >(tr -d -c '\0' | tr '\0' '\n' >&${fd_numFiles0}) | forkrun -z -k _dupefind_size

            exec {fd_numFiles0}>&-;  
            \rm -f "${dfTmpDir}"/totalCur0; 
        fi
        
       


        if [[ $(find "${dfTmpDir}"/size/dupes -maxdepth 0 -empty) ]]; then
            # no duplicate file sizes means no duplicates. Skip computing hashes.
            ${quietFlag} || printf '\nNo files with the exact same size found. \nSkipping duplicate search based on file hash.\n' >&2
            return 0
        else

            if ${quietFlag}; then
                find "${dfTmpDir}"/size/dupes/ -mindepth 1 -maxdepth 1 -printf '%P\0' | forkrun -z _dupefind_rmDupeLinks | forkrun -z _dupefind_hash
            else
                printf '\nChecking for multiple links to the same file and beginning search for files with identical sha1sum hash\n' >&2;
             
                find "${dfTmpDir}"/size/dupes/ -mindepth 1 -maxdepth 1 -printf '%P\0' | tee >(tr -d -c '\0' | tr '\0' '\n' >&${fd_numFiles1}) | forkrun -z _dupefind_rmDupeLinks | tee >(tr -d -c '\0' | tr '\0' '\n' >&${fd_numFiles2}) | forkrun -z _dupefind_hash

                exec {fd_numFiles1}>&- {fd_numFiles2}>&-;  
                \rm -f "${dfTmpDir}"/totalCur1 "${dfTmpDir}"/totalCur2;
            fi
        fi
        

        if [[ $(find "${dfTmpDir}"/size/dupes/*/hash/dupes/* -maxdepth 0 -empty) ]]; then
            ${quietFlag} || printf '\nNO DUPLICATES FOUND\n' >&2
            return 0
        else
            if ${quietFlag}; then 
                find "${dfTmpDir}" -path "${dfTmpDir}"'/size/dupes/*/hash/dupes/*' -type f | forkrun $(${quietFlag} || ! [[ -t 1 ]] || printf '-k') _dupefind_print
            else
                [ -t 1 ] || printf '\nPrinting duplicate file list to specified output file\n'
                find "${dfTmpDir}"/size/dupes -path "${dfTmpDir}"'/size/dupes/*/hash/dupes/*' -type f | tee >(tr -d -c '\0' | tr '\0' '\n' >&${fd_numFiles3}) | forkrun $(${quietFlag} || ! [[ -t 1 ]] || printf '-k') _dupefind_print 
           
                exec {fd_numFiles3}>&-
                \rm -f "${dfTmpDir}"/totalCur3
                printf '\n' >&${fd_progress}
            fi
       fi

    else

        mkdir -p "${dfTmpDir}"/hash/{data,dupes}

_dupefind_hash() (
    # function run in parallel by forkrun to find duplicate file sha1sum hashes

    set -C
    IFS=$'\n'

    local -a fHashA fNameA
    local -i kk

    # get file hash/name with 'sha1sum' and split into 2 arrays
    mapfile -t fHashA < <(sha1sum "${@}")
    mapfile -t fHashA <<<"${fHashA[*]/ /_}"
    mapfile -t fNameA <<<"${fHashA[*]#* }"
    mapfile -t fHashA <<<"${fHashA[*]%% *}"

    # add each file name to a file named using the file size under ${dfTmpDir}/hash/data using a '>' redirect
    # If the file already exists this will fail (due to set -C), meaning it is a duplicate. in this case append ('>>')
    # the filename instead and note that there are duplicate files with this hash by touching ${dfTmpDir}/hash/dupes/<hash>
     for kk in "${!fHashA[@]}"; do
        echo "${fNameA[$kk]}" >"${dfTmpDir}/hash/data/${fHashA[$kk]}" || {
            echo "${fNameA[$kk]}" >>"${dfTmpDir}/hash/data/${fHashA[$kk]}"
            : >"${dfTmpDir}/hash/dupes/${fHashA[$kk]}"
        }
    done &>/dev/null
)

_dupefind_print() (
    # print duplicate files found and (optionally) stuff to make it look nice to stdout
    local nn nnCur
    for nn in "$@"; do
        nnCur="${nn//'/hash/dupes/'/'/hash/data/'}"
        printf '\n\0' >> "${nnCur}"
            if ${quietFlag}; then
                cat "${nnCur}"
            else
                 printf '\n\n-------------------------------------------------------\SHA1 HASH: %s\n\n' "${nn##*/}" 
                 cat "${nnCur}"
            fi
    done
)

        ${quietFlag} || printf '\nBeginning search for files with identical sha1sum hash\n' >&2

        # search for duplicate file hashes by using forkrun to run _dupefind_hash
        source /proc/self/fd/0 <<<"find \"\${searchA[@]}\" ${excludeStr} -type f -print" | forkrun _dupefind_hash

       [[ $(echo "${dfTmpDir}"/hash/dupes/*) ]] && {
            ${quietFlag} || printf '\nDUPLICATES FOUND!!!\n' >&2
            find "${dfTmpDir}"/hash/dupes -type f | forkrun $(${quietFlag} || echo '-k') _dupefind_print
        }
    fi

  ) 
}
