#!/usr/bin/env bash

genOptParse() {
## READS AN OPTION PARSING DEFINITION TABLE (FROM STDIN) AND GENERATES A OPTION PARSING FUNCTION (optParse) THAT WILL PARSE THE DEFINED OPTIONS USING AN EFFICIENT CASE+LOOP
#
# USAGE:        source <(genOptParse [-p|--posix|--POSIX] [-i|--inverse] <<'EOF'
#               <OPT_PARSE_DEFINITION_TABLE>
#               EOF
#               )
#               optParse "$@"
#
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#
# LINE SYNTAX:  <MATCH_LIST> :: <VAR> [<CMD_LIST>]      [NOTE: <MATCH_LIST> may contain standard or extglob-based matches that `case` accepts.]
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
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#
# FLAGS:        Change `<FLAG>_default` variables (at top of function) to change if a flag defaults to enabled or disabled. -FLAG enables it, +FLAG disables it
#
# -p|--posix|--POSIX: use POSIX-esque option parsing. disable with +p|++posix|++POSIX. NOTE: passing '--' will always prevent further inputs from being treated as options, regardless of this flag.
#               When enabled all options must be given before all non options - the first non-option encountered will turn off option parsing. 
#               When disabled options can be intermixed with non-options.Note that if you need to use a non-option argument with the same characters as an option you must use '--' to specify the end of option parsing.
#
# -i|--inverse: ativates an optional "pre-parser" for genOptParse thgat automatically adds invedrse `+opt` flags. For options that only set 1+ "flag" variable(s) to true, this adds the analogous +OPT entries that will set those variable(s) to false. Disable with +i|++inverse.
#               EXAMPLE: option parsing definition table has line  `-a --optA :: - flagA=true` --> passing `-a` or `--optA` will set `flagA=true`
#                         -->  the inverse automatically added is  `+a ++optA :: - flagA=false` --> passing `+a` or `++optA` will set `flagA=false`
#
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#
# SPECIAL VARS: inFun: A bash array containing all NON-OPTION inputs passed to optParse. if the first N inputs are option flags (or their arguments), this is equivalent to inFun=("${@:N}")
#
# MISC NOTES:   Each line in the option parsing definition table corresponds to a single option that you want to define and parse.
#               When the code you are parsing options for is "production ready" with mostly stable options, use genOptParse without sourcing the output and then copy/paste the function it generates into the production code.
#               All options must be present BEFORE and non-option inputs. The first non-option/non-option-argument (or a '--') will stop option parsing, after which all inputs (including '-<...>' inputs) will NOT be treated as an option flag.
#               Any input starting with '-' that is encountered when option parsing is still active and is not defined in the option parsing definition table will be treated as an invalid option and dropped (with a warning on stderr)
#               optParse works by looping over options until -- or a non-option/option-argument is encountered. On each loop iteration is uses a case statement to decide what to do with the option that was given.
#
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

    local outCur i_default p_default i_flag p_flag optCur
    local -a A 
    
    shopt -s extglob
    
    # default for auto-generating the +OPT entries to set flag variables to false
    i_default=true

    # default for POSIX mode (requiring all options to come before all non-options
    p_default=true
    
    # parse options
    for optCur in "$@"; do
        case "${optCur}" in
            -?(-)p?(osix)|-?(-)POSIX)
                p_flag=true
            ;;
            -?(-)i?(nverse))
                i_flag=true
            ;;
            +?(+)p?(osix)|+?(+)POSIX)
                p_flag=false
            ;;
            +?(+)i?(nverse))
                i_flag=false
            ;;
            *)
                printf '\nWARNING: FLAG "%s" NOT RECOGNIZED. IGNORING.\n' "${optCur}" >&2
            ;;
        esac
    done
    : ${p_flag:=${p_default}} ${i_flag:=${i_default}} 
    
    # define helper functions
    ${i_flag} && {
_genOptParse_addInverse() {
    # preparser for genOptParse that looks for option table definition entries that 
    # dont have arguments and the commands being run only set (flag) variables as true and 
    # adds the analagous `+OPT` entries to disable these flag variables (set them to false)
    #
    # EXAMPLE: if entry `-?(-)v?(erbose) :: - verboseFlag=true` exists in the option parsing definition table, 
    #          then  `+?(+)v?(erbose) :: - verboseFlag=false` will automatically be added to the table 
    #
    # NOTE; IF THE OPTION DOES ANYTHING OTHER THAN SET FLAG VARIABLES TO TRUE IT WILL NOT BE AUTOMATICALLY ADDED

     { cat | tee >(cat >${fd}) >(cat | grep -E ' :: -( *[^ =]+=true;?)+ *$' | { while read -r; do printf '%s :: %s\n' "$(sed -E 's/(^| )-/\1+/g;s/((^| )((\+)|([?*+@]\()))-/\1+/g'<<<"${REPLY% :: *}")" "$(sed -E 's/=true/=false/g'<<<"${REPLY#* :: }")"; done; } >&${fd}); } {fd}>&1 | grep -vE '^$'

}
    }
_parseOptTable() {    
        # implements the line-by-line parsing of the option parsing definintion table
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
        
            matchStrCur="$(printf '%s?(=)@([[:graph:]])*' "${matchStr[0]}"; (( ${#matchStr[@]} > 1 )) && printf '|%s?(=)@([[:graph:]])*' "${matchStr[@]:1}")"
            printf '%s)\n    %s="${1##@(%s)}"\n    shift 1\n    %s\n;;\n' "${matchStrCur}" "${varAssign}" "${matchStrCur//'@([[:graph:]])*'/}" "${*}"
        
        else
        
            printf '%s' "${matchStr[0]}"
            (( ${#matchStr[@]} > 1 )) && printf '|%s' "${matchStr[@]:1}"
            printf ')\n    shift 1\n    %s\n;;\n' "${*}"
        
        fi
}

    printf '%s' '''
declare -a inFun 
inFun=()
shopt -s extglob
unset optParse

'''

printf '%s' '''
optParse() {

    local continueFlag
    
    continueFlag=true

    while ${continueFlag} && (( $# > 0  ))'''
    ${p_flag} && printf '%s' ' && [[ "$1" == [-+]* ]]'
    printf '%s' '''; do
         case "${1}" in 
'''

    if ${i_flag}; then
        {
          {
            while read -r; do
                mapfile -t A <<<"${REPLY//' '/$'\n'}"
                outCur="$(_parseOptTable "${A[@]}")"
                printf '            %s\n' "${outCur//$'\n'/$'\n'            }"
            done
          } < <(_genOptParse_addInverse <&${fd0})
        } {fd0}<&0

    else
        while read -r; do
            mapfile -t A <<<"${REPLY//' '/$'\n'}"
            outCur="$(_parseOptTable "${A[@]}")"
            printf '            %s\n' "${outCur//$'\n'/$'\n'            }"
        done
    fi

    printf '%s' '''
            --)  
                shift 1
                continueFlag=false 
                break
            ;;
            @([-+])@([[:graph:]])*)
                printf '"'"'\nWARNING: FLAG "%s" NOT RECOGNIZED. IGNORING.\n\n'"'"' "$1" >&2
                shift 1
            ;;
            *)
                continueFlag=false 
    '''
    ${p_flag} && printf '%s' '            break'
    printf '%s' '''
            ;;
        esac
        [[ $# == 0 ]] && continueFlag=false
    done    
    inFun=("${@}")
}
'''

}
