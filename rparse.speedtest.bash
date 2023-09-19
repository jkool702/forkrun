rpreparse() {
    # transform options table into a sed filter for cmdline to parse
    # the sed filter can be pre-computed and yused directly in the function instead of rebuilding it each time

    
            { grep -E '.+' | sed -E 's/^[[:space:]]*//; s/^([^-\+])/-\1/; s/^\+/\\\+/; s/^(\\?[-+])(.*) -> (.*)$/s\/^\1+\2( \\\\?[^-+].*)?.*$\/\3\/; /; s/^(\\?[-\+])(.*) => (.*) *$/s\/^\1+\2[= ]?\/\3=\/;/'; } <<'EOF'
(j|(p(rocs)?)) => nProcs
l(ines)? => nBatch
i(nsert)? -> substituteStringFlag=true
k(eep(-?order)?)? -> orderedOutFlag=true
((ks)|(keep(-?order)?-?strict)) -> orderedOutFlag=true; strictOrderedOutFlag=true
n(umber(-?lines)?)? -> exportOrderFlag=true
(([0z])|(null)) -> nullDelimiterFlag=true; pipeFlag=true
u(nescape)? -> unescapeFlag=true
((s(tdin)?)|(pipe)) -> pipeFlag=true+
t(mp)? => tmpDirRoot
d(elete)? => rmDirFlag
[\?h](elp)? -> displayHelpText
v(erbose)? -> verboseFlag=true
w(ait)? -> waitFlag=true
EOF
            
}   


rparse() {
    ## Extended-Regex sed-based options parser for bash shell functions and scripts
    #
    # Define options in table. Lines of the table can have one of 2 formats: 
    #   <REGEX> -> <CMD>    ( for options without arguments. <CMD> will be run when option is read. )
    #   <REGEX> => <VAR>    ( for options with arguments. Variable <VAR> will be set to the argument. )
    #
    # NOTE: You may include a leading dash ('-') or plus ('+') in the table regex filter. 
    #       If missing a leading dash is automatically added for you. 
    #       By default, rparse accepts options with any number of leading dashes.
    #
    # Pass the option definition table on stdin. Pass the cmdline you want to parse as function input.
    # `rparse` will output the commands that you want to run. source the output to actually run them.

    local -a ii
    local jj
    local -i nkk kk
    
    jj="${*%% -- *}"
    mapfile -t ii <<<"${jj// -/$'\n'}"
    
    nkk=0
    ii=("${@}")
    
    
    # break up options into 1 per line and then run it through the sed filter we just made
    # for options with arguments, keep the argument on the same line as its corresponding option
    
    {   
        for kk in ${!ii[@]}; do
            case "${ii[$kk]}" in
                --)
                    break; 
                ;;
                [-+]*=*)
                    printf '\n%s ' "${ii[$kk]%%=*} ${ii[$kk]#*=}"         
                    nkk=2
                ;;
                [-+]*)
                    printf '\n%s ' "${ii[$kk]}"
                    nkk=1
                ;;
                *)
                    { (( $nkk == 0 )) || (( $nkk >= 2 )); } && break
                    printf '%s ' "${ii[$kk]}"
                    ((nkk++))
                ;;
            esac
        done
        printf '\n'
    } | sed -E "${sedfilt[*]}"
}


displayHelpText() {
    local helpText 
    helpText="$(<"${BASH_SOURCE[0]}")" || helpText="$(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)"
    helpText="${helpText%%'# # # # # # # # # # BEGIN FUNCTION # # # # # # # # # #'*}"
    printf '%s\n' "${helpText//$'\n''#'/$'\n'}"
    return    
}


hh() (
# orig option parsing code

while [[ "${1,,}" =~ ^-+.+$ ]]; do
    if [[ "${1,,}" =~ ^-+(j|(n?procs?))$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
        # set number of worker coprocs
        nProcs="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+(j|(n?procs?))=?[0-9]+$ ]]; then
        # set number of worker coprocs
        nProcs="${1#*[jpJP]}"
        nProcs="${nProcs#*=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+l(ines)?$ ]] && [[ "${2}" =~ ^[0-9]+$ ]]; then
        # set number of inputs to use for each parFunc call
        nBatch="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+l(ines)?=?[0-9]+$ ]]; then
        # set number of inputs to use for each parFunc call
        nBatch="${1#*[lL]}"
        nBatch="${nBatch#*=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+i(nsert)?$ ]]; then
        # specify location to insert inputs with {} 
        substituteStringFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+i(nsert-?i)?d?$ ]]; then
        # specify location to insert inputs with {} 
        substituteStringFlag=true
        substituteStringIDFlag=true
        shift 1
    elif [[ "${1,,}" =~ ^-+k(eep(-?order)?)?$ ]]; then
        # user requested ordered output
        orderedOutFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+((ks)|(keep(-?order)?-?strict))$ ]]; then
        # user requested ordered output
        orderedOutFlag=true
        strictOrderedOutFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+n(umber(-?lines)?)?$ ]]; then
        # make output include input sorting order, but dont actually re-sort it. 
        # used internally with -k to allow for auto output re-sorting
        exportOrderFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+(([0z])|(null))$ ]]; then
        # items in stdin are seperated by NULLS, not newlines
        nullDelimiterFlag=true
        pipeFlag=true
        shift 1      
    elif [[ "${1,,}" =~ ^-+u(nescape)?$ ]]; then
        # unescape '|' '>' '>>' '||' and '&&' in args0
        unescapeFlag=true
        shift 1
    elif [[ "${1,,}" =~ ^-+((s(tdin)?)|(pipe))$ ]]; then
        # items in stdin are seperated by NULLS, not newlines
        pipeFlag=true
        shift 1    
    elif [[ "${1,,}" =~ ^-+t(mp)?$ ]] && [[ "${2}" =~ ^.+$ ]]; then
        # set tmpDir root path
        tmpDirRoot="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+t(mp)?=?.+$ ]]; then
        # set tmpDir root path
        tmpDirRoot="${1#*[tT]}"
        tmpDirRoot="${tmpDirRoot#*=}"
        shift 1
    elif [[ "${1,,}" =~ ^-+d(elete)?$ ]] && [[ "${2}" =~ ^[0-3]$ ]]; then
        # set policy to remove temp files containing data from stdin
         rmTmpDirFlag="${2}"
        shift 2
    elif [[ "${1,,}" =~ ^-+d(elete)?=?[0-3]$ ]]; then
        # set policy to remove temp files containing data from stdin
        rmTmpDirFlag="${1#**[dD]}"
        rmTmpDirFlag="${1#*=}"
        shift 1    
    elif [[ "${1,,}" =~ ^-+[\?h](elp)?$ ]]; then
        # display help
        local helpText 
        helpText="$(<"${BASH_SOURCE[0]}")" || helpText="$(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)"
        helpText="${helpText%%'# # # # # # # # # # BEGIN FUNCTION # # # # # # # # # #'*}"
        printf '%s\n' "${helpText//$'\n''#'/$'\n'}"
        return    
    elif [[ "${1,,}" =~ ^-+v(erbose)?$ ]]; then
        # increase verbosity
        verboseFlag=true
        shift 1
    elif [[ "${1,,}" =~ ^-+w(ait)?$ ]]; then
        # wait indefinately for split to output a file
        waitFlag=true
        shift 1
    elif [[ "${1}" == '--' ]]; then
        # stop processing forkrun options
        shift 1
        break
    else
        # ignore unrecognized input
        printf '%s\n' "WARNING: INPUT '${1}' NOT RECOGNIZED AS A FORKRUN OPTION. IGNORING THIS INPUT." >&2
        shift 1
    fi
done
)

# build list of ~59000 possible input combinations
mapfile -t optA < <(echo {-l\ 512,--lines=512,}\ {-j28,--nprocs=28,}\ {-i,--insert,}\ {-k,--keep-order,}\ {-n,--number-lines,}\ {-z,--null,}\ {-u,--unescape,}\ {-s,--pipe,}\ {-v,--verbose,}\ {-d\ 3,--delete=3,}$'\n')

# time sed-filter method
mapfile -t sedfilt < <(rpreparse)
time {
SECONDS=0
for kk in "${!optA[@]}"; do
    source <(rparse ${optA[$kk]})
    if [[ "$kk" == *00 ]]; then
        printf 'Finished %d of %d (%d%% complete) -- elapsed time: %d seconds (current rate: %d inputs / second)\n' $kk ${#optA[@]} $(( ( 100 * $kk ) / ${#optA[@]} )) $SECONDS $(( $kk / $SECONDS )) >&2
    fi
done
}

# time old option parsing method
time {
SECONDS=0
for kk in "${!optA[@]}"; do
    hh ${optA[$kk]}
    if [[ "$kk" == *00 ]]; then
        printf 'Finished %d of %d (%d%% complete) -- elapsed time: %d seconds (current rate: %d inputs / second)\n' $kk ${#optA[@]} $(( ( 100 * $kk ) / ${#optA[@]} )) $SECONDS $(( $kk / $SECONDS )) >&2
    fi
done
}

