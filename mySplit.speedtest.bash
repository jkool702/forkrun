#!/usr/bin/env bash 

# TL;DR SUMMARY 
# 11 tests were run on `parallel -m`, `xargs -P $(nproc) -d $'\n'`, and `mySplit`. AFAIK, these are the fastest parallelization methods supported by `parallel` and `xargs`, respectively.
# These tests computed checksums of all files under /usr (including /lib, /lib64, /bin, /sbin, ...) using 11 different checksumming algorithms. 
# Files were first copied onto a tmpfs ramdisk to ensure disk I/O did not skew results. Machine has enough RAM to ensure nothing was swapped out. 
#
# The speedtest was run on a machine with an i9-7940x (14c/28t) CPU + 128 GB RAM running on Fedora 39 with kernel 6.5.11 at a "nice level" of -20 (highest priority)
# 
# Overall results were:
# ---> in all tests mySplit was between 1.64x - 2.16x faster than `xargs -P $(nproc) -d $'\n'` and between 2.35x - 10.5x faster than `parallel -m`
# ---> on average (looking at total time between all tests), mySplit was: 1.77x the speed of `xargs -P $(nproc) -d $'\n'` and 4.46x the speed of `parallel -m`
#
# NOTE: though not shown here, when restricted to processing 1 line at a time (`parallel` ; `xargs -P $(nproc) -d $'\n' -L 1` ; `mySplit -l 1`), the performance gap is even larger:
#       mySplit tends to be at least 3-4x as fast as `xargs -P $(nproc) -d $'\n' -L 1` and >10x as fast as `parallel`

: <<'EOF'
TEST: 11 different checksums on ~496k files with a total size of ~19 GB

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY :

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       543%            354%            424%            382%            430%            557%            985%            604%            1050%           484%            235%            446%           
xargs:          169%            170%            164%            183%            164%            199%            187%            216%            197%            173%            170%            177%           
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

# choose whether or not to test parallel (defazzult is blank is true)
#testParallelFlag=false

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

"${testParallelFlag:=true}"

# CODE TO RUN SPEEDTESTS

printf '\n\n--------------------------------------------------------------------\n\nFILE COUNT/SIZE AND TIME TAKEN BY FIND COMMAND:\n\n'
time { find "${findDir}" -type f  | wc -l; }
printf '\nTOTAL SIZE OF ALL FILES: %s (%s)\n\n' "$(du -b -d 0 "${findDir}" | cut -f1)" "$(du -h -d 0 "${findDir}" | cut -f1)"

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

FILE COUNT/SIZE AND TIME TAKEN BY FIND COMMAND:

496050

real    0m0.732s
user    0m0.341s
sys     0m0.448s

TOTAL SIZE OF ALL FILES: 19012232704 (19G)



--------------------------------------------------------------------

STARTING TESTS FOR sha1sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha1sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
496050                  496050                  496050            
                                                                  
real    0m12.584s       real    0m3.917s        real    0m2.317s     
user    0m35.450s       user    0m24.077s       user    0m34.790s    
sys     0m11.603s       sys     0m7.215s        sys     0m8.830s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       543%    (443% slower than mySplit)
xargs:          169%    (69% slower than mySplit)
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
496050                  496050                  496050            
                                                                  
real    0m14.056s       real    0m6.763s        real    0m3.960s     
user    0m55.026s       user    0m55.032s       user    1m7.498s     
sys     0m11.479s       sys     0m7.265s        sys     0m8.867s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       354%    (254% slower than mySplit)
xargs:          170%    (70% slower than mySplit)
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
496050                  496050                  496050            
                                                                  
real    0m13.183s       real    0m5.106s        real    0m3.107s     
user    0m44.321s       user    0m39.888s       user    0m51.013s    
sys     0m11.358s       sys     0m7.121s        sys     0m8.814s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       424%    (324% slower than mySplit)
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
496050                  496050                  496050            
                                                                  
real    0m14.069s       real    0m6.749s        real    0m3.676s     
user    0m54.935s       user    0m55.219s       user    1m7.808s     
sys     0m11.341s       sys     0m7.411s        sys     0m9.084s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       382%    (282% slower than mySplit)
xargs:          183%    (83% slower than mySplit)
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
496050                  496050                  496050            
                                                                  
real    0m13.132s       real    0m5.010s        real    0m3.047s     
user    0m44.085s       user    0m38.793s       user    0m50.238s    
sys     0m11.318s       sys     0m7.178s        sys     0m8.784s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       430%    (330% slower than mySplit)
xargs:          164%    (64% slower than mySplit)
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
496050                  496050                  496050            
                                                                  
real    0m13.000s       real    0m4.653s        real    0m2.332s     
user    0m42.212s       user    0m28.647s       user    0m34.794s    
sys     0m11.358s       sys     0m7.092s        sys     0m8.827s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       557%    (457% slower than mySplit)
xargs:          199%    (99% slower than mySplit)
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
496050                  496050                  496050            
                                                                  
real    0m11.359s       real    0m2.158s        real    0m1.153s     
user    0m21.008s       user    0m6.516s        user    0m10.847s    
sys     0m11.612s       sys     0m7.456s        sys     0m8.468s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       985%    (885% slower than mySplit)
xargs:          187%    (87% slower than mySplit)
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
496050                  496050                  496050            
                                                                  
real    0m13.170s       real    0m4.721s        real    0m2.178s     
user    0m42.783s       user    0m28.563s       user    0m33.094s    
sys     0m11.318s       sys     0m6.787s        sys     0m8.039s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       604%    (504% slower than mySplit)
xargs:          216%    (116% slower than mySplit)
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
496050                  496050                  496050            
                                                                  
real    0m11.334s       real    0m2.133s        real    0m1.079s     
user    0m19.652s       user    0m4.879s        user    0m8.472s     
sys     0m12.071s       sys     0m7.840s        sys     0m8.442s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       1050%   (950% slower than mySplit)
xargs:          197%    (97% slower than mySplit)
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
496050                  496050                  496050            
                                                                  
real    0m12.834s       real    0m4.583s        real    0m2.647s     
user    0m41.020s       user    0m32.973s       user    0m43.793s    
sys     0m11.026s       sys     0m7.100s        sys     0m8.490s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       484%    (384% slower than mySplit)
xargs:          173%    (73% slower than mySplit)
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
496050                  496050                  496050            
                                                                  
real    0m16.543s       real    0m11.979s       real    0m7.038s     
user    1m26.377s       user    1m44.412s       user    2m4.780s     
sys     0m11.250s       sys     0m7.771s        sys     0m9.477s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       235%    (135% slower than mySplit)
xargs:          170%    (70% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

TESTS COMPLETE!!!

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       543%            354%            424%            382%            430%            557%            985%            604%            1050%           484%            235%            446%           
xargs:          169%            170%            164%            183%            164%            199%            187%            216%            197%            173%            170%            177%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           

OVERALL TIME TAKEN: 290 SECONDS

EOF
