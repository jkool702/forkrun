#!/usr/bin/env bash 

# TL;DR SUMMARY 
# 11 tests were run on `parallel -m`, `xargs -P $(nproc) -d $'\n'`, and `mySplit`. AFAIK, these are the fastest parallelization methods supported by `parallel` and `xargs`, respectively.
# These tests computed checksums of all files under /usr (including /lib, /lib64, /bin, /sbin, ...) using 11 different checksumming algorithms. 
# Files were first copied onto a tmpfs ramdisk to ensure disk I/O did not skew results. Machine has enough RAM to ensure nothing was swapped out. 
#
# The speedtest was run on a machine with an i9-7940x (14c/28t) CPU + 128 GB RAM running on Fedora with kernel 6.5.10 
# 
# Overall results were:
# ---> in all tests mySplit was between 1.53x - 2.01x faster than `xargs -P $(nproc) -d $'\n'` and between 2.1x - 9.15x faster than `parallel -m`
# ---> on average (looking at total time between all tests), mySplit was: 64% faster than `xargs -P $(nproc) -d $'\n` and 3.92x as fast as `parallel -m`
#
# NOTE: though not shown here, when restricted to processing 1 line at a time (`parallel`, `xargs -P $(nproc) -d $'\n' -L 1`, and `mySplit 1`), the performance gap is even larger:
#       mySplit tends to be at least 3-4x as fast as `xargs -P $(nproc) -d $'\n' -L 1` and >10x as fast as `parallel`

: <<'EOF'
OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       516%            335%            372%            309%            380%            475%            870%            477%            915%            442%            210%            392%           
xargs:          168%            167%            153%            159%            156%            177%            200%            179%            201%            160%            155%            164%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           
EOF

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
# a tmpfs will be automatically mounted at /mnt/ramdisk (unless a tmpfs is already mounted there) and files will be copied to /mnt/ramdisk/${findDir} using `rsync a`
ramdiskTransferFlag=true

# choose whether or not to test parallel
testParallelFlag=true

############################################## BEGIN CODE ##############################################

SECONDS=0
shopt -s extglob

declare -F mySplit 1>/dev/null 2>&1 || { [[ -f ./mySplit.bash ]] && source ./mySplit.bash; } || source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/mySplit.bash)

[[ -n "$1" ]] && [[ -d "$1" ]] && findDir="$1"
: ${findDir:="${findDirDefault}"} ${ramdiskTransferFlag:=true}

findDir="$(realpath "${findDir}")"
findDir="${findDir%/}"

TD_A=()
TD_B=()
TD_C=()
TA=()
TB=()
TC=()

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

# CODE TO RUN SPEEDTESTS

printf '\n\n--------------------------------------------------------------------\n\nFILE COUNT AND TIME TAKEN BY FIND COMMAND:\n\n'
time { find "${findDir}" -type f  | wc -l; }

"${testParallelFlag:=true}"

for nfun in "${tests[@]}"; do

	unset A B C tA tB tC tdA tdB tddA tddB vA vB N tD_C 
	
	printf '\n\n--------------------------------------------------------------------\n\nSTARTING TESTS FOR %s\n----------------------------\n\n' "$nfun" 
	
	${testParallelFlag} && { 
		printf 'Testing parallel...' >&2
		mapfile -t A < <({ 
			printf '%s\n' '-----parallel-----';
		 	time { find "${findDir}" -type f | parallel -m ${nfun} 2>/dev/null | wc -l; }; 
		 } 2>&1)
		printf '...done\n' >&2
		sleep 1
	} 

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


	${testParallelFlag} && N="$(printf '%s\n' "${A[@]}" "${B[@]}" "${C[@]}" | wc -L)" ||  N="$(printf '%s\n' "${B[@]}" "${C[@]}" | wc -L)" 

	printf '\n\nRESULTS FOR %s\n---------------------\n\n' "${nfun}"

	paste <(${testParallelFlag} && printf '%-'"$N"'s\n' "${A[@]}" || :) <(printf '%-'"$N"'s\n' "${B[@]}") <(printf '%-'"$N"'s\n' "${C[@]}")

	tC="$(printf '%s\n' "${C[@]}" | grep real | cut -f2 | sed -E 's/s$//;s/m0\.0+/m/g;s/\.//g')"; tC=$(( 60 * ${tC%%m*} + ${tC##*m} ))
	TC+=($tC)
	TD_C+=('100')

	${testParallelFlag} && { 
		tA="$(printf '%s\n' "${A[@]}" | grep real | cut -f2 | sed -E 's/s$//;s/m0\.0+/m/g;s/\.//g')"; tA=$(( 60 * ${tA%%m*} + ${tA##*m} ))
		TA+=($tA)
		tdA=$(( ( 100 * $tA ) / $tC ))	
		TD_A+=(${tdA})
		tddA=$(( $tdA - 100 ))
		[[ "$tddA" == '-'* ]] && { vA='faster'; tddA=${tddA#-}; } || vA='slower'
	}

	tB="$(printf '%s\n' "${B[@]}" | grep real | cut -f2 | sed -E 's/s$//;s/m0\.0+/m/g;s/\.//g')"; tB=$(( 60 * ${tB%%m*} + ${tB##*m} ))
	TB+=($tB)
	tdB=$(( ( 100 * $tB ) / $tC ))
	TD_B+=(${tdB})
	tddB=$(( $tdB - 100 ))
	[[ "$tddB" == '-'* ]] && { vB='faster'; tddB=${tddB#-}; } || vB='slower'

	printf '\n\nRELATIVE WALL-CLOCK TIME TAKEN\n------------------------------\n\n'

	${testParallelFlag} && { printf 'parallel: \t%s%% \t(%s%% %s than mySplit)\n' "$tdA" "$tddA" "$vA"; }
	printf 'xargs:    \t%s%% \t(%s%% %s than mySplit)\n' "$tdB" "$tddB" "$vB"
	printf 'mySplit:  \t100%%\n' 

	sleep 1

done

printf '\n\n--------------------------------------------------------------------\n\nTESTS COMPLETE!!!\n\nOVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:\n\n'

tests+=('OVERALL AVERAGE')

#${testParallelFlag} && TD_A+=($(( ( ${TD_A[0]} $(printf ' + %s' "${TD_A[@]:1}") ) / ${#TD_A[@]} )))
#TD_B+=($(( ( ${TD_B[0]} $(printf ' + %s' "${TD_B[@]:1}") ) / ${#TD_B[@]} )))
#TD_C+=(100)

tD_C=$(( ${TC[0]} $(printf ' + %s' "${TC[@]:1}") ))
TD_C+=(100)
${testParallelFlag} && TD_A+=($(( 100 * ( ${TA[0]} $(printf ' + %s' "${TA[@]:1}") ) / ${tD_C} )))
TD_B+=($(( 100 * ( ${TB[0]} $(printf ' + %s' "${TB[@]:1}") ) / ${tD_C} )))


${testParallelFlag} && mapfile -t TD_A < <(printf '%s%%\n' "${TD_A[@]}")
mapfile -t TD_B < <(printf '%s%%\n' "${TD_B[@]}")
mapfile -t TD_C < <(printf '%s%%\n' "${TD_C[@]}")

${testParallelFlag} && N=$(printf '%s\n' "${tests[@]}" "${TD_A[@]}" "${TD_B[@]}" "${TD_C[@]}" | wc -L) || N=$(printf '%s\n' "${tests[@]}" "${TD_B[@]}" "${TD_C[@]}" | wc -L)

printf '%-'"$N"'s\t' '' "${tests[@]}"
${testParallelFlag} && { 
	printf '\n\n%-'"$N"'s\t' 'parallel:'
	printf '%-'"$N"'s\t' "${TD_A[@]}"
} || printf '\n'
printf '\n%-'"$N"'s\t' 'xargs:'
printf '%-'"$N"'s\t' "${TD_B[@]}"
printf '\n%-'"$N"'s\t' 'mySplit:'
printf '%-'"$N"'s\t' "${TD_C[@]}"
printf '\n\nOVERALL TIME TAKEN: %s SECONDS\n\n' "${SECONDS}"

############################################## RESULTS ##############################################


: <<'EOF'
COPYING FILES FROM /usr TO RAMDISK AT /mnt/ramdisk/usr


--------------------------------------------------------------------

FILE COUNT AND TIME TAKEN BY FIND COMMAND:

496038

real    0m0.743s
user    0m0.345s
sys     0m0.453s


--------------------------------------------------------------------

STARTING TESTS FOR sha1sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha1sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
496038                  496038                  496038            
                                                                  
real    0m11.497s       real    0m3.752s        real    0m2.228s     
user    0m35.516s       user    0m24.262s       user    0m35.130s    
sys     0m10.916s       sys     0m7.402s        sys     0m9.074s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       516%    (416% slower than mySplit)
xargs:          168%    (68% slower than mySplit)
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
496038                  496038                  496038            
                                                                  
real    0m13.022s       real    0m6.484s        real    0m3.878s     
user    0m54.825s       user    0m55.334s       user    1m8.890s     
sys     0m10.729s       sys     0m7.526s        sys     0m9.134s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       335%    (235% slower than mySplit)
xargs:          167%    (67% slower than mySplit)
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
496038                  496038                  496019            
                                                                  
real    0m12.073s       real    0m4.989s        real    0m3.244s     
user    0m44.015s       user    0m40.269s       user    0m51.732s    
sys     0m10.739s       sys     0m7.517s        sys     0m9.078s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       372%    (272% slower than mySplit)
xargs:          153%    (53% slower than mySplit)
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
496038                  496038                  496038            
                                                                  
real    0m12.844s       real    0m6.605s        real    0m4.151s     
user    0m54.783s       user    0m55.792s       user    1m7.593s     
sys     0m10.852s       sys     0m7.811s        sys     0m8.837s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       309%    (209% slower than mySplit)
xargs:          159%    (59% slower than mySplit)
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
496038                  496038                  496038            
                                                                  
real    0m12.009s       real    0m4.946s        real    0m3.156s     
user    0m43.640s       user    0m39.981s       user    0m49.848s    
sys     0m10.990s       sys     0m7.558s        sys     0m8.906s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       380%    (280% slower than mySplit)
xargs:          156%    (56% slower than mySplit)
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
496038                  496038                  496038            
                                                                  
real    0m11.975s       real    0m4.481s        real    0m2.518s     
user    0m42.479s       user    0m28.882s       user    0m34.633s    
sys     0m10.802s       sys     0m7.530s        sys     0m9.219s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       475%    (375% slower than mySplit)
xargs:          177%    (77% slower than mySplit)
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
496038                  496038                  496038            
                                                                  
real    0m10.371s       real    0m2.384s        real    0m1.192s     
user    0m20.792s       user    0m6.230s        user    0m10.835s    
sys     0m11.080s       sys     0m7.770s        sys     0m8.944s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       870%    (770% slower than mySplit)
xargs:          200%    (100% slower than mySplit)
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
496038                  496038                  496038            
                                                                  
real    0m11.894s       real    0m4.478s        real    0m2.492s     
user    0m42.175s       user    0m28.384s       user    0m33.181s    
sys     0m10.661s       sys     0m7.265s        sys     0m8.413s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       477%    (377% slower than mySplit)
xargs:          179%    (79% slower than mySplit)
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
496038                  496038                  496038            
                                                                  
real    0m10.356s       real    0m2.277s        real    0m1.131s     
user    0m19.456s       user    0m4.584s        user    0m8.604s     
sys     0m11.463s       sys     0m7.900s        sys     0m9.327s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       915%    (815% slower than mySplit)
xargs:          201%    (101% slower than mySplit)
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
496038                  496038                  496038            
                                                                  
real    0m12.123s       real    0m4.388s        real    0m2.738s     
user    0m40.779s       user    0m33.682s       user    0m43.844s    
sys     0m10.201s       sys     0m7.424s        sys     0m8.466s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       442%    (342% slower than mySplit)
xargs:          160%    (60% slower than mySplit)
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
496038                  496038                  496038            
                                                                  
real    0m15.123s       real    0m11.167s       real    0m7.189s     
user    1m26.599s       user    1m44.586s       user    2m8.187s     
sys     0m10.631s       sys     0m7.929s        sys     0m9.574s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       210%    (110% slower than mySplit)
xargs:          155%    (55% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

TESTS COMPLETE!!!

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       516%            335%            372%            309%            380%            475%            870%            477%            915%            442%            210%            392%           
xargs:          168%            167%            153%            159%            156%            177%            200%            179%            201%            160%            155%            164%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           

OVERALL TIME TAKEN: 276 SECONDS

EOF
