#!/usr/bin/env bash 

unset tests findDir findDirDefault ramdiskTransferFlag TD_A TD_B TD_C nfun

######################################### USER SETABLE OPTIONS #########################################

# array: (test1 test2 ... testN)
# choose tests to run in speedtest. These must be codes that accept a list of multiple files as input and 
# then does something with each (for example, various checksum functions)
tests=(sha1sum sha256sum sha512sum sha224sum sha384sum md5sum 'sum -s' 'sum -r' cksum b2sum 'cksum -a sm3')

# value: path
# choose directory to run `find ____ -type f` on, which generates the file lists for the various checksums
# Note: this can also be passed as a function input to this speedtest, which will take precedence over the default value here
findDirDefault='/usr'

# value: true/false 
# decide whether to copy everything over to a tmpfs mounted at /mnt/ramdisk and run checks on those copies
# a tmpfs will be automatically mounted at /mnt/ramdisk (unless a tmpfs is slready mounted there) and files will be copied to /mnt/ramdisk/${findDir} using `rsync a`
ramdiskTransferFlag=true

############################################## BEGIN CODE ##############################################

SECONDS=0

declare -f mySplit 1>/dev/null 2>&1 || { [[ -f ./mySplit.bash ]] && source ./mySplit.bash; } || source <(curl )

[[ -n "$1" ]] && [[ -d "$1" ]] && findDir="$1"
: ${findDir:="${findDirDefault}"} ${ramdiskTransferFlag:=true}

findDir="$(realpath "${findDir}")"
findDir="${findDir%/}"

TD_A=()
TD_B=()
TD_C=()

if ${ramdiskTransferFlag}; then

	grep -qF 'tmpfs /mnt/ramdisk' </proc/mounts || {
		printf '\nMOUNTING RAMDISK AT /mnt/ramdisk\n' >&2
		mkdir -p /mnt/ramdisk
		sudo mount -t tmpfs tmpfs /mnt/ramdisk
		sudo chown -R "$USER": /mnt/ramdisk
	}
	
	printf '\nCOPYING FILES FROM %s TO RAMDISK AT %s\n' "${findDir}" "/mnt/ramdisk/${findDir#/}" >&2
	mkdir -p "/mnt/ramdisk/${findDir}"
	rsync -a "${findDir}"/* "/mnt/ramdisk/${findDir#/}"
	
	findDir="/mnt/ramdisk/${findDir#/}"

fi

printf '\n\n--------------------------------------------------------------------\n\nFILE COUNT AND TIME TAKEN BY FIND COMMAND:\n\n'

time { find "${findDir}" -type f  | wc -l; }

# CODE TO RUN SPEEDTESTS
for nfun in "${tests[@]}"; do

	unset A B C tA tB tC tdA tdB tddA tddB vA vB N 
	
	printf '\n\n--------------------------------------------------------------------\n\nSTARTING TESTS FOR %s\n----------------------------\n\n' "$nfun" 
	
	printf 'Testing parallel...' >&2
	mapfile -t A < <({ 
		printf '%s\n' '-----parallel-----';
	 	time { find "${findDir}" -type f | parallel -m ${nfun} 2>/dev/null | wc -l; }; 
	 } 2>&1)
	printf '...done\n' >&2
	sleep 1

	printf 'Testing xargs...' >&2
	mapfile -t B < <({ 
		printf '%s\n' '------xargs-------'; 
		time { find "${findDir}" -type f | xargs -P $(nproc) -d $'\n' ${nfun} 2>/dev/null | wc -l; }; 
	} 2>&1)
	printf '......done\n' >&2
	sleep 1

	printf 'Testing mySplit...' >&2
	mapfile -t C < <({ 
		printf '%s\n' '-----mySplit------'; 
		time { find "${findDir}" -type f | mySplit ${nfun} 2>/dev/null | wc -l; }; 
	} 2>&1)
	printf '....done\n' >&2
	sleep 1

	N="$(printf '%s\n' "${A[@]}" "${B[@]}" "${C[@]}" | wc -L)"

	printf '\n\nRESULTS FOR %s\n---------------------\n\n' "${nfun}"

	paste <(printf '%-'"$N"'s\n' "${A[@]}") <(printf '%-'"$N"'s\n' "${B[@]}") <(printf '%-'"$N"'s\n' "${C[@]}")

	tA="$(printf '%s\n' "${A[@]}" | grep real | cut -f2 | sed -E 's/s$//;s/m0\.0+/m/g;s/\.//g')"; tA=$(( 60 * ${tA%%m*} + ${tA##*m} ))
	tB="$(printf '%s\n' "${B[@]}" | grep real | cut -f2 | sed -E 's/s$//;s/m0\.0+/m/g;s/\.//g')"; tB=$(( 60 * ${tB%%m*} + ${tB##*m} ))
	tC="$(printf '%s\n' "${C[@]}" | grep real | cut -f2 | sed -E 's/s$//;s/m0\.0+/m/g;s/\.//g')"; tC=$(( 60 * ${tC%%m*} + ${tC##*m} ))

	tdA=$(( ( 100 * $tA ) / $tC ))
	tdB=$(( ( 100 * $tB ) / $tC ))

	TD_A+=(${tdA})
	TD_B+=(${tdB})
	TD_C+=('100')

	tddA=$(( $tdA - 100 ))
	tddB=$(( $tdB - 100 ))

	[[ "$tddA" == '-'* ]] && { vA='faster'; tddA=${tddA#-}; } || vA='slower'
	[[ "$tddB" == '-'* ]] && { vB='faster'; tddB=${tddB#-}; } || vB='slower'

	printf '\n\nRELATIVE WALL-CLOCK TIME TAKEN\n------------------------------\n\n'

	printf 'parallel: \t%s%% \t(%s%% %s than mySplit)\n' "$tdA" "$tddA" "$vA"
	printf 'xargs:    \t%s%% \t(%s%% %s than mySplit)\n' "$tdB" "$tddB" "$vB"
	printf 'mySplit:  \t100%%\n' 

	sleep 1

done

printf '\n\n--------------------------------------------------------------------\n\nTESTS COMPLETE!!!\n\nOVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:\n\n'

tests+=('OVERALL AVERAGE')

TD_A+=($(( ( ${TD_A[0]} $(printf ' + %s' "${TD_A[@]:1}") ) / ${#TD_A[@]} )))
TD_B+=($(( ( ${TD_B[0]} $(printf ' + %s' "${TD_B[@]:1}") ) / ${#TD_B[@]} )))
TD_C+=(100)

mapfile -t TD_A < <(printf '%s%%\n' "${TD_A[@]}")
mapfile -t TD_B < <(printf '%s%%\n' "${TD_B[@]}")
mapfile -t TD_C < <(printf '%s%%\n' "${TD_C[@]}")

N=$(printf '%s\n' "${tests[@]}" "${TD_A[@]}" "${TD_B[@]}" "${TD_C[@]}" | wc -L)

printf '%-'"$N"'s\t' '' "${tests[@]}"
printf '\n\n%-'"$N"'s\t' 'parallel:'
printf '%-'"$N"'s\t' "${TD_A[@]}"
printf '\n%-'"$N"'s\t' 'xargs:'
printf '%-'"$N"'s\t' "${TD_B[@]}"
printf '\n%-'"$N"'s\t' 'mySplit:'
printf '%-'"$N"'s\t' "${TD_C[@]}"
printf '\n\nOVERALL TIME TAKEN: %s SECONDS\n\n' "${SECONDS}"



# RESULTS OF SPEEDTESTS

: <<'EOF'
 

COPYING FILES FROM /usr TO RAMDISK AT /mnt/ramdisk/usr


--------------------------------------------------------------------

FILE COUNT AND TIME TAKEN BY FIND COMMAND:

483871

real    0m0.730s
user    0m0.310s
sys     0m0.471s


--------------------------------------------------------------------

STARTING TESTS FOR sha1sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha1sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483871            
                                                                  
real    0m11.828s       real    0m3.759s        real    0m2.444s     
user    0m34.449s       user    0m22.743s       user    0m32.453s    
sys     0m11.114s       sys     0m7.299s        sys     0m8.864s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       483%    (383% slower than mySplit)
xargs:          153%    (53% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

STARTING TESTS FOR sha256sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha256sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483867            
                                                                  
real    0m13.540s       real    0m6.580s        real    0m4.090s     
user    0m53.123s       user    0m52.905s       user    1m4.217s     
sys     0m10.970s       sys     0m7.672s        sys     0m9.008s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       331%    (231% slower than mySplit)
xargs:          160%    (60% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

STARTING TESTS FOR sha512sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha512sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483871            
                                                                  
real    0m12.419s       real    0m5.024s        real    0m3.046s     
user    0m42.464s       user    0m38.031s       user    0m47.074s    
sys     0m10.973s       sys     0m7.452s        sys     0m8.875s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       407%    (307% slower than mySplit)
xargs:          164%    (64% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

STARTING TESTS FOR sha224sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha224sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483871            
                                                                  
real    0m13.988s       real    0m6.767s        real    0m3.848s     
user    0m53.444s       user    0m52.436s       user    1m2.527s     
sys     0m10.833s       sys     0m7.563s        sys     0m9.097s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       363%    (263% slower than mySplit)
xargs:          175%    (75% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

STARTING TESTS FOR sha384sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha384sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483871            
                                                                  
real    0m12.433s       real    0m4.819s        real    0m3.040s     
user    0m41.933s       user    0m36.919s       user    0m46.069s    
sys     0m11.142s       sys     0m7.525s        sys     0m8.786s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       408%    (308% slower than mySplit)
xargs:          158%    (58% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

STARTING TESTS FOR md5sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR md5sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483871            
                                                                  
real    0m11.880s       real    0m4.594s        real    0m2.569s     
user    0m40.368s       user    0m27.339s       user    0m33.112s    
sys     0m11.301s       sys     0m7.397s        sys     0m8.736s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       462%    (362% slower than mySplit)
xargs:          178%    (78% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

STARTING TESTS FOR sum -s
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sum -s
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483871            
                                                                  
real    0m10.146s       real    0m2.335s        real    0m1.778s     
user    0m20.183s       user    0m6.071s        user    0m11.007s    
sys     0m11.239s       sys     0m7.733s        sys     0m8.608s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       570%    (470% slower than mySplit)
xargs:          131%    (31% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

STARTING TESTS FOR sum -r
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sum -r
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483871            
                                                                  
real    0m11.792s       real    0m4.667s        real    0m2.525s     
user    0m40.524s       user    0m27.369s       user    0m32.268s    
sys     0m10.810s       sys     0m7.148s        sys     0m8.374s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       467%    (367% slower than mySplit)
xargs:          184%    (84% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

STARTING TESTS FOR cksum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR cksum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483871            
                                                                  
real    0m10.041s       real    0m2.399s        real    0m1.841s     
user    0m18.391s       user    0m4.779s        user    0m9.839s     
sys     0m11.437s       sys     0m8.319s        sys     0m9.445s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       545%    (445% slower than mySplit)
xargs:          130%    (30% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

STARTING TESTS FOR b2sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR b2sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483871            
                                                                  
real    0m11.871s       real    0m4.323s        real    0m2.746s     
user    0m39.760s       user    0m31.939s       user    0m40.529s    
sys     0m10.706s       sys     0m7.393s        sys     0m8.439s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       432%    (332% slower than mySplit)
xargs:          157%    (57% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

STARTING TESTS FOR cksum -a sm3
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR cksum -a sm3
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483871                  483871                  483871            
                                                                  
real    0m15.972s       real    0m10.365s       real    0m6.626s     
user    1m22.871s       user    1m40.340s       user    1m58.550s    
sys     0m10.556s       sys     0m8.074s        sys     0m9.796s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       241%    (141% slower than mySplit)
xargs:          156%    (56% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

TESTS COMPLETE!!!

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       483%            331%            407%            363%            408%            462%            570%            467%            545%            432%            241%            428%           
xargs:          153%            160%            164%            175%            158%            178%            131%            184%            130%            157%            156%            158%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           

OVERALL TIME TAKEN: 280 SECONDS

EOF