#!/usr/bin/env bash 

# TL;DR SUMMARY 
# 11 tests were run on `parallel -m`, `xargs -P $(nproc) -d $'\n'`, and `mySplit`. AFAIK, these are the fastest parallelization methods supported by `parallel` and `xargs`, respectively.
# These tests computed checksums of all files under /usr (including /lib, /lib64, /bin) using 11 different checksumming algorithms. 
# Files were first copied onto a tmpfs ramdisk to ensure disk I/O did not skew results. Machine has enough RAM to ensure nothing was swapped pout. 
# 
# Overall results were:
# ---> in all tests mySplit was betwen 42% - 93% faster than `xargs -P $(nproc) -d $'\n'` and between 2.34x - 6.19x faster than `parallel -m`
# ---> on average, mySplit was: 69% faster than `xargs -P $(nproc) -d $'\n` and 4.14x as fast as `parallel -m`
#
# NOTE: though not shown here, when restricted to processing 1 line at a time (`parallel`, `xargs -P $(nproc) -d $'\n' -L 1`, and `mySplit 1`), the performance gap is even larger:
#       mySplit tends to be at least 3-4x as fast as `xargs -P $(nproc) -d $'\n' -L 1` and >10x as fast as `parallel`

: <<'EOF'

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       454%            304%            377%            314%            378%            428%            607%            439%            619%            405%            234%            414%           
xargs:          160%            175%            167%            180%            172%            181%            143%            193%            142%            168%            180%            169%           
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
testParallelFlag=false

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
	
	printf 'Testing mySplit...' >&2
	mapfile -t C < <({ 
		printf '%s\n' '-----mySplit------'; 
		time { find "${findDir}" -type f | mySplit -v ${nfun} 2>/dev/null | wc -l; }; 
	} 2>&1)
	printf '....done\n' >&2
	sleep 1

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

487099

real    0m0.728s
user    0m0.324s
sys     0m0.456s


--------------------------------------------------------------------

STARTING TESTS FOR sha1sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha1sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
487099                  487099                  487099            
                                                                  
real    0m11.286s       real    0m3.989s        real    0m2.482s     
user    0m34.069s       user    0m22.393s       user    0m33.281s    
sys     0m11.085s       sys     0m7.305s        sys     0m8.596s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       454%    (354% slower than mySplit)
xargs:          160%    (60% slower than mySplit)
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
487099                  487099                  487099            
                                                                  
real    0m12.684s       real    0m7.303s        real    0m4.166s     
user    0m53.191s       user    0m53.538s       user    1m4.341s     
sys     0m11.046s       sys     0m7.687s        sys     0m8.666s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       304%    (204% slower than mySplit)
xargs:          175%    (75% slower than mySplit)
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
487099                  487099                  487093            
                                                                  
real    0m11.782s       real    0m5.246s        real    0m3.124s     
user    0m42.423s       user    0m37.556s       user    0m48.241s    
sys     0m10.985s       sys     0m7.530s        sys     0m8.516s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       377%    (277% slower than mySplit)
xargs:          167%    (67% slower than mySplit)
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
487099                  487099                  487099            
                                                                  
real    0m12.606s       real    0m7.238s        real    0m4.014s     
user    0m52.594s       user    0m52.384s       user    1m5.200s     
sys     0m11.058s       sys     0m7.530s        sys     0m8.830s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       314%    (214% slower than mySplit)
xargs:          180%    (80% slower than mySplit)
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
487099                  487099                  487099            
                                                                  
real    0m11.858s       real    0m5.408s        real    0m3.134s     
user    0m42.200s       user    0m36.403s       user    0m47.652s    
sys     0m11.156s       sys     0m7.593s        sys     0m8.679s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       378%    (278% slower than mySplit)
xargs:          172%    (72% slower than mySplit)
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
487099                  487099                  487099            
                                                                  
real    0m11.764s       real    0m4.981s        real    0m2.747s     
user    0m40.757s       user    0m27.493s       user    0m34.379s    
sys     0m11.150s       sys     0m7.411s        sys     0m8.711s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       428%    (328% slower than mySplit)
xargs:          181%    (81% slower than mySplit)
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
487099                  487099                  487099            
                                                                  
real    0m10.071s       real    0m2.371s        real    0m1.657s     
user    0m20.072s       user    0m6.295s        user    0m11.603s    
sys     0m11.115s       sys     0m7.759s        sys     0m8.003s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       607%    (507% slower than mySplit)
xargs:          143%    (43% slower than mySplit)
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
487099                  487099                  487099            
                                                                  
real    0m11.621s       real    0m5.117s        real    0m2.646s     
user    0m40.731s       user    0m27.283s       user    0m32.941s    
sys     0m10.954s       sys     0m7.152s        sys     0m8.065s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       439%    (339% slower than mySplit)
xargs:          193%    (93% slower than mySplit)
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
487099                  487099                  487099            
                                                                  
real    0m10.153s       real    0m2.338s        real    0m1.639s     
user    0m18.702s       user    0m4.575s        user    0m10.059s    
sys     0m11.494s       sys     0m8.201s        sys     0m8.417s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       619%    (519% slower than mySplit)
xargs:          142%    (42% slower than mySplit)
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
487099                  487099                  487086            
                                                                  
real    0m11.389s       real    0m4.732s        real    0m2.811s     
user    0m39.497s       user    0m31.222s       user    0m42.009s    
sys     0m10.662s       sys     0m7.360s        sys     0m8.270s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       405%    (305% slower than mySplit)
xargs:          168%    (68% slower than mySplit)
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
487099                  487099                  487099            
                                                                  
real    0m16.620s       real    0m12.776s       real    0m7.088s     
user    1m23.550s       user    1m40.365s       user    1m59.778s    
sys     0m10.761s       sys     0m7.912s        sys     0m9.552s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       234%    (134% slower than mySplit)
xargs:          180%    (80% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

TESTS COMPLETE!!!

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       454%            304%            377%            314%            378%            428%            607%            439%            619%            405%            234%            414%           
xargs:          160%            175%            167%            180%            172%            181%            143%            193%            142%            168%            180%            169%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           

OVERALL TIME TAKEN: 283 SECONDS

EOF
