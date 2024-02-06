LC_ALL=C
LANG=C
IFS=

{ 
  dd bs=32k count="${nBytes}B" status=none
} <&${fd_read}

{ 
  head -c "${nBytes}"
} <&${fd_read}


{  
  for (( Alen=0,kk=0; Alen<${nBytes}; k++ )); do
    mapfile -d '' -n 1 -u ${fd_read} A0
    [[ $kk == 0 ]] && A=("${A0[@]}") || A[$kk]=("${A0[@]}")
    Alen=$(( Alen + ${#A[$kk]} + 1 ))
  done
}
