
fdupes() {
    ## quickly finds duplicate files using "forkrun", "du", and the "cksum" hash 
    
fdupes_help() ( cat<<'EOF'
# fdupes implements a 2 stage search: 
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
#     to skip the initial search for files with identical size,
#         pass flag '-c' or '--cksum' or '--checksum' or '--crc' or '--hash'
#     to display this help, pass flag '-h' or '-?' or '--help'
#     to prevent printing informational info to stderr, pass flag '-q' or '--quiet'
#
# OUTPUT: is split between stdout and stderr to allow for both easy interactive viewing and easy parsing
#    stdout contains the list of duplicate files found (newline-seperated),
#        with each group of duplicates additionally NULL-seperated
#    stderr contains the extra "fluff" to make interactive viewing of the output more pleasant. 
#        Redirect '2>/dev/null' or use '-q' flag to mute this.
#
# DEPENDENCIES: forkrun, find, du*, cksum        *not required with -c flag
EOF
)

    # source forkrun
    declare -F forkrun &>/dev/null || { [[ -f ./forkrun.bash ]] && source ./forkrun.bash; } || { type -p forkrun.bash &>/dev/null && source "$(type -p forkrun.bash )"; } || source <(curl 'https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash') || { printf '\nERROR!!! The forkrun function is not defined and its source code could not be found/downloaded. ABORTING!\n\n'; return 1; }

    # make vars local
    local excludeStr fdTmpDirRoot fdTmpDir nn nnCur
    local -a searchA excludeA useSizeFlag quietFlag dupes_size

    # parse inputs
    if [[ $# == 0 ]]; then
        searchA=('/')
        excludeA=('/dev' '/proc' '/sys' '/tmp')
    else
        for nn in "$@"; do
            case "${nn}" in
                -h|-\?|--help) fdupes_help; return 0 ;;
                -q|-quiet) quietFlag=true ;;
                -c|--cksum|--checksum|--crc|--hash) useSizeFlag=false ;;
                '!'*) excludeA+=("${nn#'!'}") ;;
                *) searchA+=("${nn}") ;;
            esac
        done
        
        if [[ "${searchA[*]}" == '/' ]] && [[ ${#excludeA[@]} == 0 ]]; then
            read -p "would you like to exclude /{dev,proc,sys,tmp} from your search for duplicate files? "$'\n'"(Y/n)  " -t 10 -n 1
            [[ "${REPLY}" == [nN] ]] || excludeA=('/dev' '/proc' '/sys' '/tmp')
        fi
    fi
    : "${useSizeFlag:=true}" "${quietFlag:=false}"

    # setup tmpdir for fdupes
    [[ ${fdTmpDirRoot} ]] || { [[ ${TMPDIR} ]] && [[ -d "${TMPDIR}" ]] && fdTmpDirRoot="${TMPDIR}"; } || { [[ -d '/dev/shm' ]] && fdTmpDirRoot='/dev/shm'; }  || { [[ -d '/tmp' ]] && fdTmpDirRoot='/tmp'; } || fdTmpDirRoot="$(pwd)"
    fdTmpDir="$(mktemp -p "${fdTmpDirRoot}" -d .fdupes.XXXXXX)"

    # rm tmpdir on exit
    trap '\rm -rf "${fdTmpDir:?}"' EXIT
    
    ${quietFlag} || printf '\nfdupes file data will be temporairly stored under: %s\n' "${fdTmpDir}" >&2
    
    # setup find exclusions
    printf -v excludeStr ' -path '"'"'%s'"'"' -prune -o ' "${excludeA[@]}"
    
    if ${useSizeFlag}; then
        # search for duplicate file sizes
    
        mkdir -p "${fdTmpDir}"/size/{data,dupes}
        
fdupes_size() (
    set -C
    IFS=$'\n'

    local -a fSizeA fNameA
    local -i kk

    mapfile -t fSizeA < <(du "${@}")
    mapfile -t fNameA <<<"${fSizeA[*]#*$'\t'}"
    mapfile -t fSizeA <<<"${fSizeA[*]%%$'\t'*}"

    for kk in "${!fSizeA[@]}"; do
        echo "${fNameA[$kk]}" >"${fdTmpDir}/size/data/${fSizeA[$kk]}" || {
            echo "${fNameA[$kk]}" >>"${fdTmpDir}/size/data/${fSizeA[$kk]}" 
            : >"${fdTmpDir}/size/dupes/${fSizeA[$kk]}"
        }
    done &>/dev/null
)
                
        ${quietFlag} || printf '\nBeginning search for files with identical size\n' >&2

        source /proc/self/fd/0 <<<"find \"\${searchA[@]}\" ${excludeStr} -type f -print" | forkrun fdupes_size

        mapfile -t dupes_size < <(printf '%s\n' "${fdTmpDir}"/size/dupes/*)
        if [[ ${#dupes_size[@]} == 0 ]]; then
            ${quietFlag} || printf '\nNo files with the exact same size found. \nSkipping duplicate search based on file hash.\n' >&2
            return 0
        else
            ${quietFlag} || printf '\nBeginning search for files with identical cksum (crc hash)\n' >&2
            mapfile -t dupes_size < <(cat "${dupes_size[@]//'/size/dupes/'/'/size/data/'}")
            printf '%s\n' "${dupes_size[@]}" | forkrun fdupes_hash
        fi

    else
    
        mkdir -p "${fdTmpDir}"/hash/{data,dupes}
        
fdupes_hash() (
    set -C
    IFS=$'\n'

    local -a fHashA fNameA
    local -i kk

    mapfile -t fHashA < <(cksum "${@}")
    mapfile -t fHashA <<<"${fHashA[*]/ /_}"
    mapfile -t fNameA <<<"${fHashA[*]#* }"
    mapfile -t fHashA <<<"${fHashA[*]%% *}"

    for kk in "${!fHashA[@]}"; do
        echo "${fNameA[$kk]}" >"${fdTmpDir}/hash/data/${fHashA[$kk]}" || {
            echo "${fNameA[$kk]}" >>"${fdTmpDir}/hash/data/${fHashA[$kk]}" 
            : >"${fdTmpDir}/hash/dupes/${fHashA[$kk]}"
        }
    done &>/dev/null
)

        ${quietFlag} || printf '\nBeginning search for files with identical cksum (crc hash)\n' >&2

        source /proc/self/fd/0 <<<"find \"\${searchA[@]}\" ${excludeStr} -type f -print" | forkrun fdupes_hash

    fi  


    [[ $(echo "${fdTmpDir}"/hash/dupes/*) ]] && {
        ${quietFlag} || printf '\nDUPLICATES FOUND!!!\n' >&2
        for nn in "${fdTmpDir}"/hash/dupes/*; do
            nnCur="${nn##*/}"
            ${quietFlag} || printf '\n\n-------------------------------------------------------\nCKSUM HASH: %s\n\n' "${nnCur/_/ }" >&2
            cat "${fdTmpDir}/hash/data/${nnCur}"
            printf '\0'
        done
    }
}
