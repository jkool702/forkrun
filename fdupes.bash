#!/usr/bin/env bash

fdupes() {
    ## quickly finds duplicate files using "forkrun", "du", and the "cksum" hash

fdupes_help() ( cat<<'EOF' >&2
## fdupes: quickly finds duplicate files using "forkrun", "du", and the "cksum" hash
#
# fdupes implements a 2 stage search for duplicate files:
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
# calling fdupes without any inputs is equivilant to calling 'fdupes / \!/{dev,proc,sys,tmp}'
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
                -h|-\?|--help) fdupes_help; return 0 ;;
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

    # setup tmpdir for fdupes
    [[ ${fdTmpDirRoot} ]] || { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && fdTmpDirRoot="${TMPDIR}"; } || { [[ -d '/dev/shm' ]] && fdTmpDirRoot='/dev/shm'; }  || { [[ -d '/tmp' ]] && fdTmpDirRoot='/tmp'; } || fdTmpDirRoot="$(pwd)"
    fdTmpDir="$(mktemp -p "${fdTmpDirRoot}" -d .fdupes.XXXXXX)"
    mkdir -p "${fdTmpDir}"/hash/{data,dupes}

    # rm tmpdir on exit
    trap '\rm -rf "${fdTmpDir:?}"' EXIT

    ${quietFlag} || {
        printf '\n\nfdupes will now search for duplicate files under : '
        printf "'%s' " "${searchA[@]}"
        printf '\n'
        [[ ${#excludeA[@]} == 0 ]] || { 
            printf 'the following files/directories will be excluded: '
            printf "'%s' " "${excludeA[@]}"
        }
        printf '\nfdupes file data will be temporairly stored under: %s\n\n' "${fdTmpDir}" >&2
    }

    # setup find exclusions
    printf -v excludeStr ' -path '"'"'%s'"'"' -prune -o ' "${excludeA[@]}"

fdupes_hash() (
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

    if ${useSizeFlag}; then
        # search for duplicate file sizes

        # make tmp dirs for fdupes_size
        mkdir -p "${fdTmpDir}"/size/{data,dupes}

fdupes_size() (
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
        echo "${fNameA[$kk]}" >"${fdTmpDir}/size/data/${fSizeA[$kk]}" || {
            echo "${fNameA[$kk]}" >>"${fdTmpDir}/size/data/${fSizeA[$kk]}"
            : >>"${fdTmpDir}/size/dupes/${fSizeA[$kk]}"
        }
    done &>/dev/null
)

        ${quietFlag} || printf '\nBeginning search for files with identical size\n' >&2

        # search for duplicate file sizes by using forkrun to run fdupes_size
        { source /proc/self/fd/0 <<<"find \"\${searchA[@]}\" ${excludeStr} -type f -print"; } | forkrun fdupes_size

        # take duplicates found by fdupes_size and run find duplicate file hashes from within this list
        mapfile -t dupes_size < <(printf '%s\n' "${fdTmpDir}"/size/dupes/*)
        if [[ ${#dupes_size[@]} == 0 ]]; then
            # no duplicate file sizes means no duplicates. Skip computing hashes.
            ${quietFlag} || printf '\nNo files with the exact same size found. \nSkipping duplicate search based on file hash.\n' >&2
            return 0
        else
            # search for duplicate file hashes by using forkrun to run fdupes_hash
            ${quietFlag} || printf '\nBeginning search for files with identical cksum (crc hash)\n' >&2
            dupes_size=("${dupes_size[@]//'/size/dupes/'/'/size/data/'}")
            cat "${dupes_size[@]}" | forkrun fdupes_hash
        fi

    else

        ${quietFlag} || printf '\nBeginning search for files with identical cksum (crc hash)\n' >&2

        # search for duplicate file hashes by using forkrun to run fdupes_hash
        source /proc/self/fd/0 <<<"find \"\${searchA[@]}\" ${excludeStr} -type f -print" | forkrun fdupes_hash

    fi


    # print duplicate files found to stdout and stuff to make it look nice to stderr
fdupes_print() {
    for nn in "$@"; do
            nnCur="${nn##*/}"
            ${quietFlag} || printf '\n\n-------------------------------------------------------\nCKSUM HASH: %s\n\n' "${nnCur/_/ }" >&2
            cat "${fdTmpDir}/hash/data/${nnCur}"
            printf '\0'
        done
}

    [[ $(echo "${fdTmpDir}"/hash/dupes/*) ]] && {
        ${quietFlag} || printf '\nDUPLICATES FOUND!!!\n' >&2
        printf '%s\n' "${fdTmpDir}"/hash/dupes/* | forkrun fdupes_print
    }
}
