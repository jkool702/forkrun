genOptParse() {
## READS AN OPTION PARSING DEFINITION TABLE (FROM STDIN) AND GENERATES A OPTION PARSING FUNCTION (optParse) THAT WILL PARSE THE DEFINED OPTIONS USING AN EFFICIENT CASE+LOOP
#
# USAGE:        source <({ genOptParse_pre | genOptParse; }<<'EOF'
#               <OPT_PARSE_DEFINITION_TABLE>
#               EOF
#               )
#               optParse "$@"
#
# LINE SYNTAX:  <MATCH_LIST> :: <VAR> [<CMD_LIST>]      [NOTE: <MATCH_LIST> may contain standard or extglob-based matches that `case` accepts.]
#
# REQUIREMEMTS: Option passing is "semi-POSIX-complient" in the sense that that all options must proceed any non-option arguments and that -- will prevent subsequent arguments from being treated as options. Additionally, all options must start with either a '-' or a '+'. `extglob` will automatically be enabled for the shell.
#
# <MATCH_LIST>: space-separated list of matches to use in the `case` statement match. These will be strung together seperated by '|' characters. Thesse may use extglob.
#               EXAMPLE: passing `-a --apple :: <...>` will produce `-a|--apple)` as the case match
#
# <VAR>:        variable to set using the option's argument. If the option does not have an argument set as `-` or `''`.
#               EXAMPLE: passing `-a --apple :: var_a <...>` will cause options like `-a 5` and `--apple=5` to set 'var_a' to '5'
#
# <CMD_LIST>:   (optional) list of commands to run when the option flag is given. If setting a variable (i.e., <VAR> is not '-' or '') these are run after the variable is set.
#               EXAMPLE: passing `-a --apple :: var_a echo "var_a = $var_a"` will set var_a to the option's argument and then run `echo "var_a = $var_a"`
#
# genOptParse_pre: an optional "pre-parser" for genOptParse. If your option parsing definition table contains non-argument options that only set flag variables to true, this adds the analogous +OPT entries that will set that variable to false.
#               EXAMPLE: option parsing definition table has line  `-a --optA :: - flagA=true` --> passing `-a` or `--optA` will set `flagA=true`
#                         -->  genOptParse_pre automatically adds  `+a ++optA :: - flagA=false` --> passing `+a` or `++optA` will set `flagA=false`
#
# SPECIAL VARS: inFun: A bash array containing all NON-OPTION inputs passed to optParse. if the first N inputs are option flags (or their arguments), this is equivalent to inFun=("${@:N}")
#
# MISC NOTES:   Each line in the option parsing definition table corresponds to a single option that you want to define and parse.
#               When the code you are parsing options for is "production ready" with mostly stable options, use genOptParse without sourcing the output and then copy/paste the function it generates into the production code.
#               All options must be present BEFORE and non-option inputs. The first non-option/non-option-argument (or a '--') will stop option parsing, after which all inputs (including '-<...>' inputs) will NOT be treated as an option flag.
#               Any input starting with '-' that is encountered when option parsing is still active and is not defined in the option parsing definition table will be treated as an invalid option and dropped (with a warning on stderr)
#               optParse works by looping over options until -- or a non-option/option-argument is encountered. On each loop iteration is uses a case statement to decide what to do with the option that was given.

    local outCur
    local -a A 

    cat<<'EOF'

declare -a inFun 
inFun=()
shopt -s extglob
unset optParse

optParse() {

    local continueFlag
    
    continueFlag=true
    while ${continueFlag} && (( $# > 0  )) && [[ "$1" == [\-\+]* ]]; do
         case "${1}" in 
EOF

    parseOptTable() {    
        
        local varAssign assignFlag matchStrCur
        local -a matchStr
        
        until [[ "$1" == '::' ]]; do
            matchStr+=("$1")
            shift 1
        done
        
        assignFlag=false
        [[ -z $2 ]] || [[ "$2" == '-' ]] || { assignFlag=true; varAssign="${2%$'\n'}"; }
        shift 2
        
        if ${assignFlag}; then
        
            printf '%s' "${matchStr[0]}"
            (( ${#matchStr[@]} > 1 )) && printf '|%s' "${matchStr[@]:1}"
            printf ')\n    %s="${2}"\n    shift 2\n    %s\n;;\n' "${varAssign}" "${*}"
        
            matchStrCur="$(printf '%s?(=)+([[:graph:]])' "${matchStr[0]}"; (( ${#matchStr[@]} > 1 )) && printf '|%s?(=)+([[:graph:]])' "${matchStr[@]:1}")"
            printf '%s)\n    %s="${1##@(%s)}"\n    shift 1\n    %s\n;;\n' "${matchStrCur}" "${varAssign}" "${matchStrCur//'+([[:graph:]])'/}" "${*}"
        
        else
        
            printf '%s' "${matchStr[0]}"
            (( ${#matchStr[@]} > 1 )) && printf '|%s' "${matchStr[@]:1}"
            printf ')\n    shift 1\n    %s\n;;\n' "${*}"
        
        fi
    }
    
    while read -r; do
        mapfile -t A <<<"${REPLY//' '/$'\n'}"
        outCur="$(parseOptTable "${A[@]}")"
        printf '            %s\n' "${outCur//$'\n'/$'\n'            }"
    done
    
    cat<<'EOF'
            '--')  
                shift 1
                continueFlag=false 
                break
            ;;
            \-*)
                printf '\nWARNING: FLAG "%s" NOT RECOGNIZED. IGNORING.\n\n' "$1"
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

}

genOptParse_pre() {
    # preparser for genOptParse that looks for option table definition entries that 
    # dont have arguments and the commands being run only set (flag) variables as true and 
    # adds the analagous `+OPT` entries to disable these flag variables (set them to false)
    #
    # EXAMPLE: if entry `-?(-)v?(erbose) :: - verboseFlag=true` exists in the option parsing definition table, 
    #          then  `+?(+)v?(erbose) :: - verboseFlag=false` will automatically be added to the table 
    #
    # NOTE: IF THE OPTION DOES ANYTHING OTHER THAN SET FLAG VARIABLES TO TRUE IT WILL NOT BE AUTOMATICALLY ADDED

     { cat | tee >(cat >${fd}) >(cat | grep -E ' :: -( *[^ =]+=true;?)+ *$' | { while read -r; do printf '%s :: %s\n' "$(sed -E 's/(^| )-/\1+/g;s/((^| )\+?([?*+@]\()?)-(\))/\1+\2/g'<<<"${REPLY% :: *}")" "$(sed -E 's/=true/=false/g'<<<"${REPLY#* :: }")"; done; } >&${fd}); } {fd}>&1 | grep -vE '^$'

}
