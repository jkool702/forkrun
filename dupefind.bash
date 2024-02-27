#!/usr/bin/env bash

dupefind() {
    ## quickly finds duplicate files using "forkrun", "du", and the "cksum" hash

dupefind_help() ( cat<<'EOF' >&2
## dupefind: quickly finds duplicate files using "forkrun", "du", and the "cksum" hash
#
# dupefind implements a 2 stage search for duplicate files:
#    it first finds files that have identical sizes, then
#    for these files, it computes the cksum hash and looks for matching hashes
#
# INPUTS: are directories to look for duplicate files under (at any depth level)
#
# inputs starting with `!` will be excluded from this duplicate search
#     dont forget to quote/escape the '!': use '!/path' or \!/path
#
# if you want to look for duplicates under a directory starting with a '!' or '-h'
#     then use the full path (e.g. use '/${PWD}/!whyyyy', not '!whyyyy')
#
# calling dupefind without any inputs is equivilant to calling 'dupefind / \!/{dev,proc,sys,tmp}'
#
# FLAGS:
#     to skip the initial search for files with identical size, pass flag '-c' or '--cksum' or '--checksum' or '--crc' or '--hash'
#     to display this help, pass flag '-h' or '-?' or '--help'
#     to prevent printing informational info to stderr, pass flag '-q' or '--quiet'
#
# OUTPUT: is split between stdout and stderr to allow for both easy interactive viewing and easy parsing
#
#    stdout contains the list of duplicate files found (newline-seperated),
#        with each group of duplicates additionally NULL-seperated
#
#    stderr contains the extra "fluff" to make interactive viewing of the output more pleasant
#        redirect '2>/dev/null' or use the '-q' flag to mute this
#
# DEPENDENCIES: forkrun, find, du*, cksum        *not required with -c flag
EOF
)

    set +C

    # source forkrun
    declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source ./forkrun.bash; } || { type -p forkrun.bash &>/dev/null && source "$(type -p forkrun.bash )"; } || source <(curl 'https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash') || { printf '\nERROR!!! The forkrun function is not defined and its source code could not be found/downloaded. ABORTING!\n\n'; return 1; }

    # make vars local
    local excludeStr fdTmpDirRoot fdTmpDir nn nnCur
    local -a searchA excludeA useSizeFlag quietFlag dupes_size

    # parse inputs
    : "${useSizeFlag:=true}" "${quietFlag:=false}"
    if [[ $# == 0 ]]; then
        # set default runtime values
        searchA=('/')
        excludeA=('/dev' '/proc' '/sys' '/tmp')
    else
        # loop over inputs
        for nn in "$@"; do
            case "${nn}" in
                -h|-\?|--help) dupefind_help; return 0 ;;
                -q|-quiet) quietFlag=true ;;
                -c|--cksum|--checksum|--crc|--hash) useSizeFlag=false ;;
                '!'*) excludeA+=("${nn#'!'}") ;;
                *) searchA+=("${nn}") ;;
            esac
        done

        [[ ${#searchA[@]} == 0 ]] && searchA=('/')

        # if doing a full system search 'everything under /' and not using -q flag check if they want to skip '/dev' '/proc' '/sys' '/tmp'
        if [[ "${searchA[*]}" == '/' ]] && ! ${quietFlag}; then
            for nnCur in '/dev' '/proc' '/sys' '/tmp'; do
                ( IFS=' '; [[ " ${excludeA[*]} " == *' '"${nnCur}"?(/)' '* ]] ) || read -p "would you like to exclude ${nnCur} from your search for duplicate files? "$'\n'"(Y/n)  " -t 10 -n 1
                [[ "${REPLY}" == [nN] ]] || excludeA+=("${nnCur}")
            done
        fi
    fi

    # setup tmpdir for dupefind
    [[ ${fdTmpDirRoot} ]] || { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && fdTmpDirRoot="${TMPDIR}"; } || { [[ -d '/dev/shm' ]] && fdTmpDirRoot='/dev/shm'; }  || { [[ -d '/tmp' ]] && fdTmpDirRoot='/tmp'; } || fdTmpDirRoot="$(pwd)"
    fdTmpDir="$(mktemp -p "${fdTmpDirRoot}" -d .dupefind.XXXXXX)"

    # rm tmpdir on exit
    trap '\rm -rf "'"${fdTmpDir}"'"' EXIT

    ${quietFlag} || {
        printf '\n\ndupefind will now search for duplicate files under : '
        printf "'%s' " "${searchA[@]}"
        printf '\n'
        [[ ${#excludeA[@]} == 0 ]] || { 
            printf 'the following files/directories will be excluded: '
            printf "'%s' " "${excludeA[@]}"
        }
        printf '\ndupefind file data will be temporairly stored under: %s\n\n' "${fdTmpDir}" >&2
    }

    # setup find exclusions
    printf -v excludeStr ' -path '"'"'%s'"'"' -prune -o ' "${excludeA[@]}"


    if ${useSizeFlag}; then
        # search for duplicate file sizes

        # make tmp dirs for dupefind_size
        mkdir -p "${fdTmpDir}"/size/{data,dupes}

dupefind_size() (
    # function run in parallel by forkrun to find duplicate files size

    set -C
    IFS=$'\n'

    local -a fSizeA fNameA
    local -i kk

    # get file size/name with 'du' and split into 2 arrays
    mapfile -t fSizeA < <(du "${@}")
    mapfile -t fNameA <<<"${fSizeA[*]#*$'\t'}"
    mapfile -t fSizeA <<<"${fSizeA[*]%%$'\t'*}"

    # add each file name to a file named using the file size under ${fdTmpDir}/size/data using a '>' redirect
    # If the file already exists this will fail (due to set -C), meaning it is a duplicate. in this case append ('>>')
    # the filename instead and note that there are multiple files with this size by touching ${fdTmpDir}/size/dupes/<filesize>
    for kk in "${!fSizeA[@]}"; do
        echo "${fSizeA[$kk]}"$'\034'"${fNameA[$kk]}" >"${fdTmpDir}/size/data/${fSizeA[$kk]}" || {
            echo "${fSizeA[$kk]}"$'\034'"${fNameA[$kk]}" >>"${fdTmpDir}/size/data/${fSizeA[$kk]}"
            [[ -d "${fdTmpDir}/size/dupes/${fSizeA[$kk]}" ]] || mkdir -p "${fdTmpDir}/size/dupes/${fSizeA[$kk]}"
        }
    done &>/dev/null
)

dupefind_hash() (
    # function run in parallel by forkrun to find duplicate file cksum hashes

    set -C
    IFS=$'\n'

    local -a fHashA fSizeA fNameA
    local -i kk

    # get file hash/size/name with 'cksum' and split into 3 arrays
    fSizeA=("${@%%$'\034'*}")
    fNameA=("${@##*$'\034'}")
    mapfile -t fHashA < <(cksum "${fNameA[@]}")
    mapfile -t fHashA <<<"${fHashA[*]/ /_}"
    mapfile -t fHashA <<<"${fHashA[*]%% *}"

#    for kk in ${!fHashA[@]}; do
#        printf 'name: %s  ;  size: %s  ;  hash: %s\n' "${fNameA[$kk]}" "${fSizeA[$kk]}" "${fHashA[$kk]}" >&2
#    done

    # add each file name to a file named using the file size under ${fdTmpDir}/hash/data using a '>' redirect
    # If the file already exists this will fail (due to set -C), meaning it is a duplicate. in this case append ('>>')
    # the filename instead and note that there are duplicate files with this hash by touching ${fdTmpDir}/hash/dupes/<hash>
     for kk in "${!fHashA[@]}"; do
        mkdir -p "${fdTmpDir}/size/dupes/${fSizeA[$kk]}/hash"/{data,dupes}
        echo "${fNameA[$kk]}" >"${fdTmpDir}/size/dupes/${fSizeA[$kk]}/hash/data/${fHashA[$kk]}" || {
            echo "${fNameA[$kk]}" >>"${fdTmpDir}/size/dupes/${fSizeA[$kk]}/hash/data/${fHashA[$kk]}"
            : >"${fdTmpDir}/size/dupes/${fSizeA[$kk]}/hash/dupes/${fHashA[$kk]}"
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
                nnSize="${nn##"${fdTmpDir}/size/dupes/"}"
                printf '\n\n-------------------------------------------------------\nCKSUM HASH: %s\nFILE SIZE: %s\n\n' "${nn##*/}" "${nnSize%%/*}" 
                cat "${nnCur}"
            fi
    done
)


        ${quietFlag} || printf '\nBeginning search for files with identical size\n' >&2

        # search for duplicate file sizes by using forkrun to run dupefind_size
        { source /proc/self/fd/0 <<<"find \"\${searchA[@]}\" ${excludeStr} -type f -print"; } | forkrun dupefind_size

        # take duplicates found by dupefind_size and run find duplicate file hashes from within this list
        mapfile -t dupes_size < <(printf '%s\n' "${fdTmpDir}"/size/dupes/*)
        if [[ ${#dupes_size[@]} == 0 ]]; then
            # no duplicate file sizes means no duplicates. Skip computing hashes.
            ${quietFlag} || printf '\nNo files with the exact same size found. \nSkipping duplicate search based on file hash.\n' >&2
            return 0
        else
            # search for duplicate file hashes by using forkrun to run dupefind_hash
            ${quietFlag} || printf '\nBeginning search for files with identical cksum (crc hash)\n' >&2
            dupes_size=("${dupes_size[@]//'/size/dupes/'/'/size/data/'}")
            cat "${dupes_size[@]}" | forkrun dupefind_hash
        fi

        [[ $(echo "${fdTmpDir}"/size/dupes/*/hash/dupes/*) ]] && {
            ${quietFlag} || printf '\nDUPLICATES FOUND!!!\n' >&2
            find "${fdTmpDir}"/size/dupes/*/hash/dupes/ -type f | forkrun $(${quietFlag} || echo '-k') dupefind_print
        }

    else

        mkdir -p "${fdTmpDir}"/hash/{data,dupes}

dupefind_hash() (
    # function run in parallel by forkrun to find duplicate file cksum hashes

    set -C
    IFS=$'\n'

    local -a fHashA fNameA
    local -i kk

    # get file hash/name with 'cksum' and split into 2 arrays
    mapfile -t fHashA < <(cksum "${@}")
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
                 printf '\n\n-------------------------------------------------------\nCKSUM HASH: %s\n\n' "${nn##*/}" 
                 cat "${nnCur}"
            fi
    done
)

        ${quietFlag} || printf '\nBeginning search for files with identical cksum (crc hash)\n' >&2

        # search for duplicate file hashes by using forkrun to run dupefind_hash
        source /proc/self/fd/0 <<<"find \"\${searchA[@]}\" ${excludeStr} -type f -print" | forkrun dupefind_hash

       [[ $(echo "${fdTmpDir}"/hash/dupes/*) ]] && {
            ${quietFlag} || printf '\nDUPLICATES FOUND!!!\n' >&2
            find "${fdTmpDir}"/hash/dupes -type f | forkrun $(${quietFlag} || echo '-k') dupefind_print
        }
    fi
    
}
