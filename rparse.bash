#!/usr/bin/env bash

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
    
    local -a sedfilt0 ii
    local -i nkk kk
    
    nkk=0
    ii=("${@}")
    
    # transform options table into a sed filter for cmdline to parse
    {
        mapfile -t sedfilt0 < <(cat <&${fd0} | grep -E '.+' | sed -E 's/^[[:space:]]*//; s/^([^-\+])/-\1/; s/^\+/\\\+/; s/^(\\?[-+])(.*) -> (.*)$/s\/^\1+\2( \\\\?[^-+].*)?.*$\/\3\/; /; s/^(\\?[-\+])(.*) => (.*) *$/s\/^\1+\2[= ]\/\3=\/;/')
    } {fd0}<&0
    
   
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
    } | sed -E "${sedfilt0[*]}"
}


# define testing function
gg() {
local sedfilt flagA valB valB2
flagA=false

# define options table
# if option '-a' or '--apple' is given, the command `flagA=true` is run. If using + instead of - then `flagA=false` is run instead
# if '-b <...>' or '--bananna <...>' or '--bananna=<...>' is given, set variable "valB" to <...> (i.e., run `valB=<...>`). If using + instead of - then `valB2` is set instead
sedfilt="$(cat<<'EOF'
a(pple)? -> flagA=true
+a(pple)? -> flagA=false
-b(anannas?)? => valB
+b(anannas?)? => valB2
EOF
)"

# pass rparse the option table on its stdin and the commandline as function inputs, then source its output
source <({ rparse "$@"; }<<<"${sedfilt}")

# check things were set correctly
echo "flagA = ${flagA}"
echo "valB = ${valB}"
echo "valB2 = ${valB2}"

# do stuff probably
}

# try it out
gg
gg -a
gg -apple
gg -a +a 
gg -b 0
gg --bananna=1
gg -a ++bananna=2
gg -b 3 --apple --bananna 4 +a
gg -a --bananna 4 -b 3 ++apple +bananna=2 -a -b=1 func arg nonoption
