# # # # #  OPTPARSE TEST EXAMPLES # # # # #

source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/optParse.bash)

# GENERATE SIMPLE OPTION PARSING DEFINITION TABLE AND PASS TO GENOPTPARSE TO GENERATE THE OPTPARSE FUNCTION, AND SOURCE IT. THIS PARTICULAR TABLE RESULTS IN:
#    -a|--apple (no arg)     -->  flag_a=true
#    -b|--bananna{ ,=}<arg>  -->  var_b=<arg>
#    -c|--coconut{ ,=}<arg>  -->  var_c=<arg>; flag_c=true

source <({ genOptParse; }<<'EOF'
-a --apple :: - flag_a=true
-b --bananna :: var_b
-c --coconut :: var_c flag_c=true
EOF
)

# this should give the following optparse function code
:<<'EOF'
declare -a inFun 
inFun=()
shopt -s extglob
unset optParse


optParse() {

    local continueFlag
    
    continueFlag=true

    while ${continueFlag} && (( $# > 0  )) && [[ "$1" == [-+]* ]]; do
         case "${1}" in 
            -a|--apple)
                shift 1
                flag_a=true
            ;;
            -b|--bananna)
                var_b="${2}"
                shift 2
                
            ;;
            -b?(=)@([[:graph:]])*|--bananna?(=)@([[:graph:]])*)
                var_b="${1##@(-b?(=)|--bananna?(=))}"
                shift 1
                
            ;;
            -c|--coconut)
                var_c="${2}"
                shift 2
                flag_c=true
            ;;
            -c?(=)@([[:graph:]])*|--coconut?(=)@([[:graph:]])*)
                var_c="${1##@(-c?(=)|--coconut?(=))}"
                shift 1
                flag_c=true
            ;;
            +a|++apple)
                shift 1
                flag_a=false
            ;;

            --)  
                shift 1
                continueFlag=false 
                break
            ;;
            @([-+])@([[:graph:]])*)
                printf '\nWARNING: FLAG "%s" NOT RECOGNIZED. IGNORING.\n\n' "$1" >&2
                shift 1
            ;;
            *)
                continueFlag=false 
                break
            ;;
        esac
        [[ $# == 0 ]] && continueFlag=false
    done    
    inFun=("${@}")
}
EOF

# RUN A TEST
unset flag_a var_b flag_c var_c
optParse --apple -b 55 --coconut='yum' 'nonOpt0' 'nonOpt1' 'nonOpt2' 'etc...'

# CHECK RESULTS
printf '\n\nSET VARIABLES:\n\n'
printf '%s = %s\n' 'flag_a' "$flag_a" 'var_b' "$var_b" 'flag_c' "$flag_c" 'var_c' "$var_c"
printf '\n\nREMAINING INPUTS:  '
printf '"%s" ' "${inFun[@]}"
printf '\n\n'
    
# THE ABOVE CHECK *SHOULD* OUTPUT THE FOLLOWING
:<<'EOF'
SET VARIABLES:

flag_a = true
var_b = 55
flag_c = true
var_c = yum


REMAINING INPUTS:  "nonOpt0" "nonOpt1" "nonOpt2" "etc..." 
EOF

# HARDER TEST EXAMPLE + SPEEDTEST: PARSING FORKRUN's OPTIONS

# build list of ~59000 possible input combinations (between 1-10 option flags passed)
mapfile -t optA < <(echo {-l\ 512,--lines=512,}\ {-j28,--nprocs=28,}\ {-i,--insert,}\ {-k,--keep-order,}\ {-n,--number-lines,}\ {-z,--null,}\ {-u,--unescape,}\ {-s,--pipe,}\ {-v,--verbose,}\ {-d\ 3,--delete=3,}$'\n')

# setup new option parsing definition table
unset optParse inFun 
source <(genOptParse<<'EOF'
-?(-)j -?(-)P -?(-)?(n)proc?(s) :: nProcs
-?(-)l?(ine?(s)) :: nBatch
-?(-)t?(mp?(?(-)dir)) :: tmpDirRoot
-?(-)d?(elete) :: rmTmpDirFlag 
-?(-)i?(nsert) :: - substituteStringFlag=true
-?(-)I?(D) -?(-)INSERT?(?(-)ID) :: - substituteStringFlag=true; substituteStringIDFlag=true
-?(-)k?(eep?(?(-)order)) :: - orderedOutFlag=true
-?(-)K?(EEP?(?(-)ORDER)?(?(-)STRICT)) :: - orderedOutFlag=true; strictOrderedOutFlag=true
-?(-)n?(umber)?(-)?(line?(s)) :: - exportOrderFlag=true
-?(-)0 -?(-)z -?(-)null :: - nullDelimiterFlag=true
-?(-)u?(nescape) :: - unescapeFlag=true
-?(-)s?(tdin) -?(-)pipe :: - pipeFlag=true
-?(-)w?(ait) :: - waitFlag=true
-?(-)v?(erbose) :: - verboseFlag=true
-?(-)h?(elp) :: - displayHelp
EOF
)

# time auto-generated case loop option parsing method
# on my system the overall average speed for all 59k combinations is ~6000/sec --> Average time to parse 5 +/- 5 options is ~ 180 microseconds
time {
SECONDS=0
shopt -s extglob
for kk in "${!optA[@]}"; do
    optParse ${optA[$kk]}
    if [[ "$kk" == *00 ]]; then
        printf 'Finished %d of %d (%d%% complete) -- elapsed time: %d seconds (current rate: %d inputs / second)\n' $kk ${#optA[@]} $(( ( 100 * $kk ) / ${#optA[@]} )) $SECONDS $(( $kk / ( 1 + $SECONDS ) )) >&2
    fi
done
}
