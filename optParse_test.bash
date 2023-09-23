genOptParse() {
## READS AN OPTION PARSING DEFINITION TABLE (FROM STDIN) AND GENERATES A OPTION PARSING FUNCTION: optParse
#
# USAGE:        source <(genOptParse_pre<<'EOF' | genOptParse
#               <OPT_PARSE_DEFINITION_TABLE>
#               EOF
#               )
#               optParse "$@"
#
# LINE SYNTAX:  <MATCH_LIST> :: <VAR> [<CMD_LIST>]
#
# <MATCH_LIST>: space-seperated list of matches to use in the `case` statement match. These will be strung together seperated by '|' characters. 
#               EXAMPLE: passing `-a --apple :: <...>` will produce `-a|--apple)` as the case match
#
# <VAR>:        variable to set using the option's argument. If the option does not have an argument set as `-` or `''`.
#               EXAMPLE: passing `-a --apple :: var_a <...>` will cause options like `-a 5` and `--apple=5` to set 'var_a' to '5'
#
# <CMD_LIST>:   (optional) list of commands to run when flag is given. If setting a variable (i.e., <VAR> is not '-' or '') these are run after the variable is set.
#               EXAMPLE: passing `-a --apple :: var_a echo "var_a = $var_a"`
#
# SPECIAL VARS: In addition to setting variables as defined in the option parsing definition table, optparse will set 1 additional variables (arrays):
# --> inFun:    bash array containing all inputs passed to optParse. if the first N inputs are option flags (or their arguments), this is equivilant to "${@:N}"
#
# MISC NOTES:   Each line in the option parsing definition table corresponds to a single option that you want to define and parse.
#               When the code you are parsing options for is "production ready" with mostly stable options, use genOptParse without sourcing the output and then copy/paste the function it generates into the production code.
#               All options must be present BEFORE and non-option inputs. The first non-option/non-option-argument (or a '--') will stop option parsing, after which all inputs (including '-<...>' inputs) will NOT be treated as an option flag.
#               Any input starting with '-' that is encountered wwhen option parsing is still active and is not defined in the option parsing definition table will be treated as an invalid option and dropped (with a warning on stderr)
#               optParse works by using the "callback function" feature in `mapfile`. Mapfile loads everything into an array, and after reading each element _optParse is called, which in turn determines what to do with that input.

    local outCur
    local -a A 

    cat<<'EOF'

declare -a inFun 
inFun=()

optParse() {
    
    local assignNextVar assignDoneFlag
    local -a inAll
    
    assignDoneFlag=false
    
    _optParse() {

        if ${assignDoneFlag}; then
            inFun+=("$2")

        elif [[ ${assignNextVar} ]]; then 
            
            { source /proc/self/fd/0; }<<<"${assignNextVar}=\"$2\"" 
            assignNextVar=''

        else
            case "$2" in 
                --)  
                    assignDoneFlag=true  
                ;;
EOF

    parseOptTable() {    
        
        local varAssign assignFlag
        local -a matchStr
        
        until [[ "$1" == '::' ]]; do
            matchStr+=("$1")
            shift 1
        done
        
        assignFlag=false
        [[ -z $2 ]] || [[ "$2" == '-' ]] || { assignFlag=true; varAssign="$2"; }
        shift 2
        
        if ${assignFlag}; then
        
            printf '%s' "${matchStr[0]}"
            (( ${#matchStr[@]} > 1 )) && printf '|%s' "${matchStr[@]:1}"
            printf ')\n    assignNextVar=%s\n    %s\n;;\n' "${varAssign}" "${*}"
        
            printf '%s=*' "${matchStr[0]}"
            (( ${#matchStr[@]} > 1 )) && printf '|%s=*' "${matchStr[@]:1}"
            printf ')\n    %s="${2#*=}"\n    %s\n;;\n' "${varAssign}" "${*}"
        
        else
        
            printf '%s' "${matchStr[0]}"
            (( ${#matchStr[@]} > 1 )) && printf '|%s' "${matchStr[@]:1}"
            printf ')\n    %s\n;;\n' "${*}"
        
        fi
    }
    
    while read -r; do
        mapfile -t -d ' ' A <<<"${REPLY}"
        outCur="$(parseOptTable "${A[@]}")"
        printf '                %s\n' "${outCur//$'\n'/$'\n'                }"
    done
    
    cat<<'EOF'
                -*)
                    printf '\nWARNING: FLAG "%s" NOT RECOGNIZED. IGNORING.\n\n' "$2"
                ;;
                *)
                    inFun+=("$2")
                    assignDoneFlag=true
                ;;
            esac
        fi
    }     
    
    mapfile -t -d '' -C _optParse -c 1 inAll < <(printf '%s\0' "$@")
}
EOF

}

genOptParse_pre() {
    # preparser for genOptParse that looks for option table definition entries that 
    # dont have arguments and the commands being run only set (flag) variables as true and 
    # adds the analagous `+OPT` entries to disable these flag variables (set them to false)
    #
    # EXAMPLE: if entry `-?(-)v?(erbose) :: - verboseFlag=true` exists in the option parsing definition table, 
    #          then  `+?(+)v?(erbose) :: - verboseFlag=false` will automatically be added to the table 
    #
    # NOTE; IF THE OPTION DOES ANYTHING OTHER THAN SET FLAG VARIABLES TO TRUE IT WILL NOT BE AUTOMAGICALLY ADDED

     { cat | tee >(cat >${fd}) >(cat | grep -E ' :: -( *[^ =]+=true;?)+ *$' | { while read -r; do printf '%s :: %s\n' "$(sed -E 's/(^| )-/\1+/g;s/((^| )\+?[?*+@]\()-\)/\1+)/g'<<<"${REPLY% :: *}")" "$(sed -E 's/=true/=false/g'<<<"${REPLY#* :: }")"; done; } >&${fd}); } {fd}>&1 | grep -vE '^$'

}

# # # # #  TEST EXAMPLE # # # # #

# GENERATE SIMPLE OPTION PARSING DEFINITION TABLE AND PASS TO GENOPTPARSE TO GENERATE THE OPTPARSE FUNCTION, AND SOURCE IT. THIS PARTICULAR TABLE RESULTS IN:
#    -a|--apple (no arg)     -->  flag_a=true
#    -b|--bananna{ ,=}<arg>  -->  var_b=<arg>
#    -c|--coconut{ ,=}<arg>  -->  var_c=<arg>; flag_c=true

source <(genOptParse_pre<<'EOF' | genOptParse
-a --apple :: - flag_a=true
-b --bananna :: var_b
-c --coconut :: var_c flag_c=true
EOF
)

# THE ABOVE CODE PRODUCES THE FOLLOWING FUNCTION DEFINITION, WHICH IS THEN SOURCED
#
# NOTE: IT IS MORE EFFICIENT TO TAKE THIS GENERATED FUNCTION AND COPY/PASTE IT INTO THE  
#       CODE YOU ARE PARSING OPTIONS FOR INSTEAD OF [RE]GENERATING+SOURCING IT EVERY TIME

:<<'EOI'
declare -a inFun inAll
inFun=()
inAll=()

optParse() {
    
    local assignNextVar assignDoneFlag 
    
    assignDoneFlag=false
    
    _optParse() {

        if ${assignDoneFlag}; then
            inFun+=("$2")

        elif [[ ${assignNextVar} ]]; then 
            
            { source /proc/self/fd/0; }<<<"${assignNextVar}=\"$2\"" 
            assignNextVar=''

        else
            case "$2" in 
                --)  
                    assignDoneFlag=true  
                ;;
                -a|--apple)
                    flag_a=true
                ;;
                -b|--bananna)
                    assignNextVar=var_b
                    
                ;;
                -b=*|--bananna=*)
                    var_b="${2#*=}"
                    
                ;;
                -c|--coconut)
                    assignNextVar=var_c
                    flag_c=true
                ;;
                -c=*|--coconut=*)
                    var_c="${2#*=}"
                    flag_c=true
                ;;
                -*)
                    printf '\nWARNING: FLAG "%s" NOT RECOGNIZED. IGNORING.\n\n' "$2"
                ;;
                *)
                    inFun+=("$2")
                    assignDoneFlag=true
                ;;
            esac
        fi
    }     
    
    mapfile -t -d '' -C _optParse -c 1 inAll < <(printf '%s\0' "$@")
}
EOI

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
