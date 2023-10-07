#!/usr/bin/env bash 

# TL;DR SUMMARY 
# 11 tests were run on `parallel -m`, `xargs -P $(nproc) -d $'\n'`, and `mySplit`. AFAIK, these are the fastest parallelization methods supported by `parallel` and `xargs`, respectively.
# These tests computed checksums of all files under /usr (including /lib, /lib64, /bin) using 11 different checksumming algorithms. 
# Files were first copied onto a tmpfs ramdisk to ensure disk I/O did not skew results. Machine has enough RAM to ensure nothing was swapped pout. 
# 
# Overall results were:
# ---> in all tests mySplit was at minimum: at least 31% faster than `xargs -P $(nproc) -d $'\n` and at least 2.56x as fast as `parallel -m`
# ---> on average, mySplit was: 62% faster than `xargs -P $(nproc) -d $'\n` and 4.42x as fast as `parallel -m`
#
# NOTE: though not shown here, when restricted to processing 1 line at a time (`parallel`, `xargs -P $(nproc) -d $'\n' -L 1`, and `mySplit 1`), the performance gap is even larger:
#       mySplit tends to be 3-4x as fast as xargs and >10x as fast as parallel 

: <<'EOF'

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       493%            358%            433%            350%            415%            480%            579%            495%            565%            442%            256%            442%           
xargs:          155%            173%            170%            168%            161%            178%            135%            183%            131%            166%            168%            162%           
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
# a tmpfs will be automatically mounted at /mnt/ramdisk (unless a tmpfs is slready mounted there) and files will be copied to /mnt/ramdisk/${findDir} using `rsync a`
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

483876

real    0m0.737s
user    0m0.310s
sys     0m0.479s


--------------------------------------------------------------------

STARTING TESTS FOR sha1sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha1sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
483876                  483876                  483876            
                                                                  
real    0m11.703s       real    0m3.679s        real    0m2.372s     
user    0m34.047s       user    0m21.980s       user    0m32.243s    
sys     0m11.293s       sys     0m7.336s        sys     0m8.768s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       493%    (393% slower than mySplit)
xargs:          155%    (55% slower than mySplit)
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
483876                  483876                  483876            
                                                                  
real    0m13.584s       real    0m6.551s        real    0m3.786s     
user    0m52.903s       user    0m52.536s       user    1m2.655s     
sys     0m10.965s       sys     0m7.660s        sys     0m9.144s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       358%    (258% slower than mySplit)
xargs:          173%    (73% slower than mySplit)
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
483876                  483876                  483876            
                                                                  
real    0m12.549s       real    0m4.934s        real    0m2.897s     
user    0m42.324s       user    0m37.467s       user    0m47.204s    
sys     0m10.980s       sys     0m7.668s        sys     0m8.928s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       433%    (333% slower than mySplit)
xargs:          170%    (70% slower than mySplit)
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
483876                  483876                  483876            
                                                                  
real    0m13.576s       real    0m6.514s        real    0m3.870s     
user    0m52.940s       user    0m52.098s       user    1m3.716s     
sys     0m11.066s       sys     0m7.565s        sys     0m9.070s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       350%    (250% slower than mySplit)
xargs:          168%    (68% slower than mySplit)
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
483876                  483876                  483876            
                                                                  
real    0m12.339s       real    0m4.796s        real    0m2.969s     
user    0m42.086s       user    0m36.347s       user    0m46.262s    
sys     0m11.232s       sys     0m7.520s        sys     0m9.100s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       415%    (315% slower than mySplit)
xargs:          161%    (61% slower than mySplit)
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
483876                  483876                  483876            
                                                                  
real    0m12.256s       real    0m4.569s        real    0m2.553s     
user    0m40.487s       user    0m27.537s       user    0m33.054s    
sys     0m11.028s       sys     0m7.469s        sys     0m8.851s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       480%    (380% slower than mySplit)
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
483876                  483876                  483876            
                                                                  
real    0m10.289s       real    0m2.405s        real    0m1.775s     
user    0m20.180s       user    0m6.329s        user    0m11.110s    
sys     0m11.460s       sys     0m7.833s        sys     0m8.787s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       579%    (479% slower than mySplit)
xargs:          135%    (35% slower than mySplit)
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
483876                  483876                  483876            
                                                                  
real    0m12.212s       real    0m4.535s        real    0m2.467s     
user    0m40.843s       user    0m26.970s       user    0m31.895s    
sys     0m10.970s       sys     0m7.124s        sys     0m8.258s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       495%    (395% slower than mySplit)
xargs:          183%    (83% slower than mySplit)
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
483876                  483876                  483876            
                                                                  
real    0m10.069s       real    0m2.332s        real    0m1.780s     
user    0m18.845s       user    0m4.614s        user    0m9.599s     
sys     0m11.628s       sys     0m8.151s        sys     0m9.016s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       565%    (465% slower than mySplit)
xargs:          131%    (31% slower than mySplit)
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
483876                  483876                  483876            
                                                                  
real    0m11.713s       real    0m4.409s        real    0m2.650s     
user    0m39.212s       user    0m31.812s       user    0m40.515s    
sys     0m10.636s       sys     0m7.364s        sys     0m8.536s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       442%    (342% slower than mySplit)
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
483876                  483876                  483876            
                                                                  
real    0m16.315s       real    0m10.722s       real    0m6.364s     
user    1m23.890s       user    1m40.664s       user    1m58.190s    
sys     0m10.750s       sys     0m8.013s        sys     0m9.841s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       256%    (156% slower than mySplit)
xargs:          168%    (68% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

TESTS COMPLETE!!!

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       493%            358%            433%            350%            415%            480%            579%            495%            565%            442%            256%            442%           
xargs:          155%            173%            170%            168%            161%            178%            135%            183%            131%            166%            168%            162%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           

OVERALL TIME TAKEN: 283 SECONDS

EOF
