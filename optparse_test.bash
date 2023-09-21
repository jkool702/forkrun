#!/usr/bin/env bash

gg() {
    
    local -a inAll inFun
    local -i kk
    local assignNextFlag assignDoneFlag flag_a var_b flag_c var_c
    
    assignNextFlag=false
    assignDoneFlag=false
    flag_a=false
    flag_b=false
    flag_c=false
    
    optParse() {
        
        if ${assignDoneFlag}; then
            inFun+=("$2")
            
        elif ${assignNextFlag}; then 
            varAssign="$2"
            assignNextFlag=false
            decalre +n varAssign
        
        else
            case "$2" in 
                --)  
                    assignDoneFlag=true  
                ;;
                -a|--apple)  
                    flag_a=true
                ;;
                -b|--bananna)
                    declare -n varAssign=var_b
                    assignNextFlag=true
                ;;
                -b=|--bananna=)
                    var_b="${2#*=}"
                ;;
                -c|--coconut)
                    declare -n varAssign=var_c
                    assignNextFlag=true
                    flag_c=true
                ;;
                -c=|--coconut=)
                    var_c="${2#*=}"
                    flag_c=true
                ;;
                *)
                    printf '\nWARNING: FLAG "%s" NOT RECOGNIZED. IGNORING.\n\n' "$2"
                ;;
            esac
        fi
    }     
    
    mapfile -t -d '' -C optParse -c 1 inAll <(printf '%s\0' "$@")

    printf '\nSET VARIABLES:\n\n'
    printf '%s = %s\n' 'flag_a' "$flag_a" 'var_b' "$var_b" 'flag_c' "$flag_c" 'var_c' "$var_c"
    printf '\n\nNON_OPTION_INPUTS\n\n'
    printf '"%s" ' "${inFun[@]}"

}

gg --apple -b 55 --coconut 'yum' 'nonOpt0' 'nonOpt1' 'nonOpt2' 'etc...'
