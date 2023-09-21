#                             Online Bash Shell.
#                 Code, Compile, Run and Debug Bash script online.
# Write your code in this editor and press "Run" button to execute it.

#!/usr/bin/env bash

gg() {
    
    local -a inAll inFun
    local assignNextFlag assignDoneFlag flag_a var_b flag_c var_c varAssign
    
    assignNextFlag=''
    assignDoneFlag=false
    flag_a=false
    flag_c=false
    
    optParse() {
        
        if ${assignDoneFlag}; then
            inFun+=("$2")

        elif [[ ${assignNextFlag} ]]; then 
            declare -ng varAssign=${assignNextFlag}
            varAssign="$2" 
            declare +ng varAssign
            assignNextFlag=''
        else
            case "$2" in 
                --)  
                    assignDoneFlag=true  
                ;;
                -a|--apple)  
                    flag_a=true
                ;;
                -b|--bananna)
                    assignNextFlag=var_b
                ;;
                -b=|--bananna=)
                    var_b="${2#*=}"
                ;;
                -c|--coconut)
                    assignNextFlag=var_c
                    flag_c=true
                ;;
                -c=|--coconut=)
                    var_c="${2#*=}"
                    flag_c=true
                ;;
                -*)
                    printf '\nWARNING: FLAG "%s" NOT RECOGNIZED. IGNORING.\n\n' "$2"
                ;;
                *)
                    inFun+=("$2")
                    assignDoneFlag=true
            esac
        fi
    }     
    
    mapfile -t -d '' -C optParse -c 1 inAll <(printf '%s\0' "$@")

    printf '\nSET VARIABLES:\n\n'
    printf '%s = %s\n' 'flag_a' "$flag_a" 'var_b' "$var_b" 'flag_c' "$flag_c" 'var_c' "$var_c"
    printf '\n\nNON_OPTION_INPUTS\n\n'
    printf '%q' "${inFun[@]}"
    
    }
    
    gg "$@"
