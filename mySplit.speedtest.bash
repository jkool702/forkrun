#!/usr/bin/env bash 

# TL;DR SUMMARY 
# 11 tests were run on `parallel -m`, `xargs -P $(nproc) -d $'\n'`, and `mySplit`. AFAIK, these are the fastest parallelization methods supported by `parallel` and `xargs`, respectively.
# These tests computed checksums of all files under /usr (including /lib, /lib64, /bin) using 11 different checksumming algorithms. 
# Files were first copied onto a tmpfs ramdisk to ensure disk I/O did not skew results. Machine has enough RAM to ensure nothing was swapped pout. 
# 
# Overall results were:
# ---> in all tests mySplit was betwen 38% - 87% faster than `xargs -P $(nproc) -d $'\n'` and between 2.38x as fast 6.07x faster than `parallel -m`
# ---> on average, mySplit was: 67% faster than `xargs -P $(nproc) -d $'\n` and 4.12x as fast as `parallel -m`
#
# NOTE: though not shown here, when restricted to processing 1 line at a time (`parallel`, `xargs -P $(nproc) -d $'\n' -L 1`, and `mySplit 1`), the performance gap is even larger:
#       mySplit tends to be at least 3-4x as fast as `xargs -P $(nproc) -d $'\n' -L 1` and >10x as fast as `parallel`

: <<'EOF'

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       451%            311%            378%            314%            368%            431%            607%            441%            591%            407%            238%            412%           
xargs:          163%            172%            166%            185%            162%            186%            140%            187%            138%            166%            177%            167%           
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

############################################## BEGIN CODE ##############################################

SECONDS=0

declare -F mySplit 1>/dev/null 2>&1 || { [[ -f ./mySplit.bash ]] && source ./mySplit.bash; } || source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/mySplit.bash)

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

############################################## RESULTS ##############################################


: <<'EOF'
COPYING FILES FROM /usr TO RAMDISK AT /mnt/ramdisk/usr


--------------------------------------------------------------------

FILE COUNT AND TIME TAKEN BY FIND COMMAND:

487099

real    0m0.735s
user    0m0.306s
sys     0m0.480s


--------------------------------------------------------------------

STARTING TESTS FOR sha1sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha1sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
487099                  487099                  487079            
                                                                  
real    0m11.230s       real    0m4.075s        real    0m2.489s     
user    0m34.300s       user    0m22.392s       user    0m33.254s    
sys     0m11.134s       sys     0m7.262s        sys     0m8.864s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       451%    (351% slower than mySplit)
xargs:          163%    (63% slower than mySplit)
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
                                                                  
real    0m12.645s       real    0m7.005s        real    0m4.065s     
user    0m52.915s       user    0m52.066s       user    1m4.459s     
sys     0m11.135s       sys     0m7.798s        sys     0m8.773s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       311%    (211% slower than mySplit)
xargs:          172%    (72% slower than mySplit)
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
487099                  487099                  487099            
                                                                  
real    0m11.980s       real    0m5.278s        real    0m3.169s     
user    0m42.805s       user    0m37.206s       user    0m48.982s    
sys     0m11.090s       sys     0m7.533s        sys     0m8.732s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       378%    (278% slower than mySplit)
xargs:          166%    (66% slower than mySplit)
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
                                                                  
real    0m12.648s       real    0m7.482s        real    0m4.026s     
user    0m52.875s       user    0m53.307s       user    1m4.235s     
sys     0m10.952s       sys     0m7.738s        sys     0m8.788s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       314%    (214% slower than mySplit)
xargs:          185%    (85% slower than mySplit)
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
                                                                  
real    0m11.770s       real    0m5.206s        real    0m3.197s     
user    0m42.140s       user    0m36.215s       user    0m47.696s    
sys     0m11.080s       sys     0m7.532s        sys     0m8.561s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       368%    (268% slower than mySplit)
xargs:          162%    (62% slower than mySplit)
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
                                                                  
real    0m11.633s       real    0m5.030s        real    0m2.695s     
user    0m40.517s       user    0m27.707s       user    0m34.268s    
sys     0m11.055s       sys     0m7.397s        sys     0m8.581s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       431%    (331% slower than mySplit)
xargs:          186%    (86% slower than mySplit)
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
                                                                  
real    0m10.156s       real    0m2.349s        real    0m1.672s     
user    0m20.099s       user    0m6.174s        user    0m11.672s    
sys     0m11.068s       sys     0m7.718s        sys     0m8.153s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       607%    (507% slower than mySplit)
xargs:          140%    (40% slower than mySplit)
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
487099                  487099                  487085            
                                                                  
real    0m11.722s       real    0m4.966s        real    0m2.654s     
user    0m41.148s       user    0m27.140s       user    0m32.903s    
sys     0m10.907s       sys     0m7.116s        sys     0m8.003s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       441%    (341% slower than mySplit)
xargs:          187%    (87% slower than mySplit)
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
                                                                  
real    0m10.028s       real    0m2.350s        real    0m1.694s     
user    0m18.680s       user    0m4.707s        user    0m10.194s    
sys     0m11.470s       sys     0m8.171s        sys     0m8.699s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       591%    (491% slower than mySplit)
xargs:          138%    (38% slower than mySplit)
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
487099                  487099                  487085            
                                                                  
real    0m11.517s       real    0m4.704s        real    0m2.829s     
user    0m39.619s       user    0m31.362s       user    0m41.681s    
sys     0m10.760s       sys     0m7.237s        sys     0m8.269s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       407%    (307% slower than mySplit)
xargs:          166%    (66% slower than mySplit)
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
                                                                  
real    0m16.498s       real    0m12.300s       real    0m6.919s     
user    1m24.005s       user    1m39.218s       user    2m0.063s     
sys     0m10.776s       sys     0m8.154s        sys     0m9.669s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       238%    (138% slower than mySplit)
xargs:          177%    (77% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

TESTS COMPLETE!!!

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       451%            311%            378%            314%            368%            431%            607%            441%            591%            407%            238%            412%           
xargs:          163%            172%            166%            185%            162%            186%            140%            187%            138%            166%            177%            167%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           

OVERALL TIME TAKEN: 282 SECONDS

EOF
