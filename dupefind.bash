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

dupefind_help() ( cat<<'EOF' >&2
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
    local excludeStr fdTmpDirRoot fdTmpDir nn nnCur sizeCutoff realpathFlag PID0
    local -a searchA excludeA useSizeFlag quietFlag autoExcludeFlag 

    PID0=$$

    type -p realpath &>/dev/null && realpathFlag=true || realpathFlag=false

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
                -h|-\?|--help) dupefind_help; return 0 ;;
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
    [[ ${fdTmpDirRoot} ]] || { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && fdTmpDirRoot="${TMPDIR}"; } || { [[ -d '/dev/shm' ]] && fdTmpDirRoot='/dev/shm'; }  || { [[ -d '/tmp' ]] && fdTmpDirRoot='/tmp'; } || fdTmpDirRoot="$(pwd)"
    fdTmpDir="$(mktemp -p "${fdTmpDirRoot}" -d .dupefind.XXXXXX)"

    # rm tmpdir on exit
    trap '\rm -rf "${fdTmpDir}"' EXIT INT HUP TERM

    ${quietFlag} || {
        printf '\n\ndupefind will now search for duplicate files under : '
        printf "'%s' " "${searchA[@]}"
        printf '\n'
        [[ ${#excludeA[@]} == 0 ]] || { 
            printf 'the following files/directories will be excluded: '
            printf "'%s' " "${excludeA[@]}"
        }
        printf '\ndupefind file data will be temporairly stored under: %s\n\n' "${fdTmpDir}" 
    } >&2

    # setup find exclusions
    printf -v excludeStr ' -path '"'"'%s'"'"' -prune -o ' "${excludeA[@]}"


    if ${useSizeFlag}; then
        # search for duplicate file sizes

        # make tmp dirs for dupefind_size
        mkdir -p "${fdTmpDir}"/size/{data,dupes} 


dupefind_progress() { (
    # Prints progress of current operation to screen
    local numFilesCur numFilesAll percentCur unknownFlag


    numFilesAll="$1"
    shift 1
    if { [[ ${numFilesAll} ]] && (( ${numFilesAll} > 0 )); }; then
        unknownFlag=false 
    else
        unknownFlag=true
    fi

    {
        SECONDS=0
        printf '\n\n--------------------------------------------------------------------------------\nPROGRESS: %s\n\nCOMPLETED\t/\tTOTAL\t( %% )\n0\t/\t%s%s' "${*}" "$(${unknownFlag} && echo "???"|| echo "${numFilesAll}")" "$(${unknownFlag} || printf '\t( 0%% ) ')" >&${fd2}
        numFilesCur=0
        while true; do
            read -r -u ${fd_progress}
            [[ ${REPLY} ]] || break
            numFilesCur+=${REPLY}
            ${unknownFlag} && {
                if [[ -f /proc/${PID0}/fdinfo/${fd_numFiles} ]]; then
                    read -r numFilesAll </proc/$PID0/fdinfo/${fd_numFiles}
                    numFilesAll="${numFilesAll#*$'\t'}"
                else
                    unknownFlag=false
                fi
            }
            if { [[ ${numFilesAll} ]] && (( ${numFilesAll} > 0 )); }; then
                percentCur="$(( 100 * ${numFilesCur} / ${numFilesAll} ))"
                printf '\%s\t/\t%s\t( %s )' "${numFilesCur}" "${numFilesAll}" "${percentCur}" >&${fd2}
            else
                printf '\rCOMPLETED: \t%s' "${numFilesCur}" >&${fd2}
            fi
        done
        printf '\n\nSTAGE FINISHED!!!\n\nTIME TAKEN: %s SECONDS\n\n' "${SECONDS}" >&${fd2}
    } &
) {fd2}>&2
}

dupefind_size() (
    # function run in parallel by forkrun to find duplicate files size

    set -C
#    set -v
    shopt -s extglob
#    IFS=$'\n'

    local -a fSizeA fNameA  
    local -i kk
    local fHash0

    # get file size/name with 'du' and split into 2 arrays
    mapfile -t -d '' fSizeA < <(du -b -0 "${@}")
    fNameA=("${fSizeA[@]#*$'\t'}")
    fSizeA=("${fSizeA[@]%%$'\t'*}")

    ${realpathFlag} && mapfile -t -d '' fNameA < <(realpath -z "${fNameA[@]}")

    # add each file name to a file named using the file size under ${fdTmpDir}/size/data using a '>' redirect
    # If the file already exists this will fail (due to set -C), meaning it is a duplicate. in this case append ('>>')
    # the filename instead and note that there are multiple files with this size by touching ${fdTmpDir}/size/dupes/<filesize>
    for kk in "${!fSizeA[@]}"; do
        [[ ${fSizeA[$kk]} == +([0-9]) ]] || continue   

        (( ${fSizeA[$kk]} > $sizeCutoff )) && {
            fHash0="$({ dd if="${fNameA[$kk]}" bs=64k count=1 iflag=fullblock status=none; dd if="${fNameA[$kk]}" bs=64k count=1 iflag=fullblock status=none skip=$(( ${fSizeA[$kk]} - 65536 ))B; } | sha1sum)"
            printf -v 'fSizeA['"$kk"']' '%s_%s' "${fSizeA[$kk]}" "${fHash0% -}"
        }

        if [[ -d "${fdTmpDir}/size/dupes/${fSizeA[$kk]}" ]]; then
            printf '%s\034%s\0' "${fSizeA[$kk]}" "${fNameA[$kk]}" >>"${fdTmpDir}/size/data/${fSizeA[$kk]}"
        else
            printf '%s\034%s\0' "${fSizeA[$kk]}" "${fNameA[$kk]}" >"${fdTmpDir}/size/data/${fSizeA[$kk]}" || {
                printf '%s\034%s\0' "${fSizeA[$kk]}" "${fNameA[$kk]}" >>"${fdTmpDir}/size/data/${fSizeA[$kk]}"
                [[ -s "${fdTmpDir}/size/dupes/${fSizeA[$kk]}/link" ]] || {
                    mkdir -p "${fdTmpDir}/size/dupes/${fSizeA[$kk]}"
                    ln -s "${fdTmpDir}/size/data/${fSizeA[$kk]}" "${fdTmpDir}/size/dupes/${fSizeA[$kk]}/link"
                }
            }
        fi 
    done &>/dev/null

    ${quietFlag} || printf '%s\n' "${#fNameA[@]}" >&${fd_progress}
)

dupefind_hash() (
    # function run in parallel by forkrun to find duplicate file sha1sum hashes

    set -C
#    set -v
#    IFS=$'\n'

    local -a fHashA fSizeA fNameA 
    local -i kk

    # get file size/name[/hash-partial] from name and compute hash[-partial] with 'sha1sum' and split into 3/4 arrays
    fSizeA=("${@%%$'\034'*}")
    fNameA=("${@#*$'\034'}")
    
    mapfile -t -d '' fHashA < <(sha1sum -z "${fNameA[@]}" 2>&1)
    fHashA=("${fHashA[@]%%?(sha1sum:) *}")

    #${realpathFlag} && mapfile -t -d '' fNameA < <(realpath -z "${fNameA[@]}")

    # add each file name to a file named using the file size under ${fdTmpDir}/size/dupes/<size>/hash/data using a '>' redirect
    # If the file already exists this will fail (due to set -C), meaning it is a duplicate. in this case append ('>>')
    # the filename instead and note that there are duplicate files with this hash by touching ${fdTmpDir}/size/dupes/<size>/hash/dupes/<hash>
     for kk in "${!fHashA[@]}"; do
        [[ -z ${fHashA[$kk]} ]] && continue

        [[ -d "${fdTmpDir}/size/dupes/${fSizeA[$kk]}/hash" ]] || mkdir -p "${fdTmpDir}/size/dupes/${fSizeA[$kk]}/hash"/{data,dupes}

        printf '%s\n\0' "${fNameA[$kk]}" >"${fdTmpDir}/size/dupes/${fSizeA[$kk]}/hash/data/${fHashA[$kk]}" || {
            printf '%s\n\0' "${fNameA[$kk]}" >>"${fdTmpDir}/size/dupes/${fSizeA[$kk]}/hash/data/${fHashA[$kk]}"
            [[ -f "${fdTmpDir}/size/dupes/${fSizeA[$kk]}/hash/dupes/${fHashA[$kk]}" ]] || : >"${fdTmpDir}/size/dupes/${fSizeA[$kk]}/hash/dupes/${fHashA[$kk]}"
        }
    done &>/dev/null

    ${quietFlag} || printf '%s\n' "${#fNameA[@]}" >&${fd_progress}
)

#dupefind_unique() (
#    local nn 
#    local -a allCurA
#    shopt -s extglob
#
#   for nn in "$@"; do
#
#        mapfile -t -d '' allCurA <"${nn}"
#        printf '%s\0' "${allCurA[@]}" | sort -u -z -t$'\034' -k2 >"${nn}"
#    done
#
#)

dupefind_print() (
    # print duplicate files found and (optionally) stuff to make it look nice to stdout
    local nn nnCur
    for nn in "$@"; do
        nnCur="${nn%'/hash/dupes/'*}/hash/data/${nn##*/}"
        printf '\n\0' >> "${nnCur}"
            if ${quietFlag} || ! [ -t 1 ]; then
                cat "${nnCur}"
            else
                nnSize="${nn##"${fdTmpDir}/size/dupes/"}"
                printf '\n\n-------------------------------------------------------\nCKSUM HASH: %s\nFILE SIZE: %s\n\n' "${nn##*/}" "${nnSize%%/*}" 
                cat "${nnCur}"
            fi
    done

    ${quietFlag} || printf '%s\n' "${#}" >&${fd_progress}

)



        # search for duplicate file sizes by using forkrun to run dupefind_size
        : >"${fdTmpDir}"/totalCur
        {
            ${quietFlag} || { printf '\nBeginning search for files with identical size\n' >&2; dupefind_progress '' 'CHECKING FILE SIZES FOR IDENTICALLY SIZED FILES'; }
            { source /proc/self/fd/0 <<<"find \"\${searchA[@]}\" ${excludeStr} -type f -print0"; } | tee >(tr -c -d '\0' >&${fd_numFiles}) | forkrun -z -k dupefind_size
            ${quietFlag} || { printf '\n' >&${fd_progress}; exec {fd_numFiles}>&-; }
        } {fd_numFiles}>"${fdTmpDir}"/totalCur
        \rm -f "${fdTmpDir}"/totalCur;

        if [[ $(find "${fdTmpDir}"/size/dupes -maxdepth 0 -empty) ]]; then
            # no duplicate file sizes means no duplicates. Skip computing hashes.
            ${quietFlag} || printf '\nNo files with the exact same size found. \nSkipping duplicate search based on file hash.\n' >&2
            return 0
        else
            #printf '%s/0' "${dupes_size0[@]}" "${dupes_size1[@]}" | forkrun -z dupefind_unique

            # search for duplicate file hashes by using forkrun to run dupefind_hash
            : >"${fdTmpDir}"/totalCur
            {
                ${quietFlag} || { printf '\nBeginning search for files with identical sha1sum hash\n' >&2; dupefind_progress '' 'COMPUTING SHA1SUM HASH FOR FILES WITH IDENTICAL SIZES'; }
                find "${fdTmpDir}"/size/dupes/ -name 'link' | forkrun -i -u -l1 'cat' '{} | sort -u -z' | tee >(tr -c -d '\0' >&${fd_numFiles}) | forkrun -z dupefind_hash 
                ${quietFlag} || { printf '\n' >&${fd_progress}; exec {fd_numFiles}>&-;}
            } {fd_numFiles}>"${fdTmpDir}"/totalCur
            \rm -f "${fdTmpDir}"/totalCur; 
        fi

        if [[ $(find "${fdTmpDir}"/size/dupes/*/hash/dupes/* -maxdepth 0 -empty) ]]; then
            ${quietFlag} || printf '\nNO DUPLICATES FOUND\n' >&2
            return 0
        else
            : >"${fdTmpDir}"/totalCur
            {
                ${quietFlag} || { printf '\nDUPLICATES FOUND!!!\n' >&2; [ -t 1 ] || dupefind_progress "$(tr -d '\n' <"${fdTmpDir}"/.fileListCur | tr '\0' '\n' | wc -l)" 'SAVING DUPLICATE LIST TO OUTPUT FILE'; }
                find "${fdTmpDir}" -path "${fdTmpDir}"'/size/dupes/*/hash/dupes/*' -type f | tee >(tr -c -d '\0' >&${fd_numFiles}) | forkrun $(${quietFlag} || ! [[ -t 1 ]] || printf '-k') dupefind_print <"${fdTmpDir}"/.fileListCur 
                ${quietFlag} || [ -t 1 ] ||  { printf '\n' >&${fd_progress}; exec {fd_numFiles}>&-; }
            } {fd_numFiles}>"${fdTmpDir}"/totalCur
            \rm -f "${fdTmpDir}"/totalCur; 
        fi

    else

        mkdir -p "${fdTmpDir}"/hash/{data,dupes}

dupefind_hash() (
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

    # add each file name to a file named using the file size under ${fdTmpDir}/hash/data using a '>' redirect
    # If the file already exists this will fail (due to set -C), meaning it is a duplicate. in this case append ('>>')
    # the filename instead and note that there are duplicate files with this hash by touching ${fdTmpDir}/hash/dupes/<hash>
     for kk in "${!fHashA[@]}"; do
        echo "${fNameA[$kk]}" >"${fdTmpDir}/hash/data/${fHashA[$kk]}" || {
            echo "${fNameA[$kk]}" >>"${fdTmpDir}/hash/data/${fHashA[$kk]}"
            : >"${fdTmpDir}/hash/dupes/${fHashA[$kk]}"
        }
    done &>/dev/null
)

dupefind_print() (
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

        # search for duplicate file hashes by using forkrun to run dupefind_hash
        source /proc/self/fd/0 <<<"find \"\${searchA[@]}\" ${excludeStr} -type f -print" | forkrun dupefind_hash

       [[ $(echo "${fdTmpDir}"/hash/dupes/*) ]] && {
            ${quietFlag} || printf '\nDUPLICATES FOUND!!!\n' >&2
            find "${fdTmpDir}"/hash/dupes -type f | forkrun $(${quietFlag} || echo '-k') dupefind_print
        }
    fi

  ) {fd_progress}<><(:)
}
