#!/usr/bin/env bash 

# TL;DR SUMMARY 
# 11 tests were run on `parallel -m`, `xargs -P $(nproc) -d $'\n'`, and `mySplit`. AFAIK, these are the fastest parallelization methods supported by `parallel` and `xargs`, respectively.
# These tests computed checksums of all files under /usr (including /lib, /lib64, /bin, /sbin, ...) using 11 different checksumming algorithms. 
# Files were first copied onto a tmpfs ramdisk to ensure disk I/O did not skew results. Machine has enough RAM to ensure nothing was swapped out. 
#
# The speedtest was run on a machine with an i9-7940x (14c/28t) CPU + 128 GB RAM running on Fedora 39 with kernel 6.5.11 at a "nice level" of -20 (highest priority)
# 
# Overall results were:
# ---> on average (looking at total time between all tests), mySplit was around 1.7x as fast `xargs -P $(nproc) -d $'\n'` and around 7.3x as fast as `parallel -m`
# ---> in all tests mySplit was between 1.42x - 2.73x faster than `xargs -P $(nproc) -d $'\n'` and between 3.64x - 15.39x faster than `parallel -m`
#
# NOTE: though not shown here, when restricted to processing 1 line at a time (`parallel` ; `xargs -P $(nproc) -d $'\n' -L 1` ; `mySplit -l 1`), the performance gap is even larger:
#       mySplit tends to be at least 3-4x as fast as `xargs -P $(nproc) -d $'\n' -L 1` and >10x as fast as `parallel`

: <<'EOF'
TEST: 11 different checksums on ~496k files with a total size of ~19 GB

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       941%            590%            714%            576%            751%            887%            1539%           914%            1660%           802%            364%            730%           
xargs:          172%            168%            142%            161%            152%            176%            216%            181%            273%            153%            172%            170%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           

OVERALL TIME TAKEN: 381 SECONDS
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

renice --priority -20 --pid $$

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
# SOME PERF STATS AND OS INFO (FEDORA 39)

> uname -a

Linux localhost 6.5.11-300.fc39.x86_64 #1 SMP PREEMPT_DYNAMIC Wed Nov  8 22:37:57 UTC 2023 x86_64 GNU/Linux

# PERF stats on running all 11 checksums on all ~490k files with 5x runs (total time is for all 11 checksums)

Performance counter stats for '/bin/bash -c shopt -s extglob; source /mnt/ramdisk/mySplit.bash; for nfun in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3"; do find /mnt/ramdisk/usr -type f | mySplit ${nfun} | wc -l;  done' (5 runs):

        615,162.80 msec task-clock                       #   18.436 CPUs utilized               ( +-  0.05% )
         2,077,977      context-switches                 #    3.378 K/sec                       ( +-  0.62% )
           555,112      cpu-migrations                   #  902.382 /sec                        ( +-  1.37% )
         6,066,132      page-faults                      #    9.861 K/sec                       ( +-  0.06% )
 2,481,708,765,918      cycles                           #    4.034 GHz                         ( +-  0.04% )  (50.68%)
 3,991,554,098,630      instructions                     #    1.61  insn per cycle              ( +-  0.01% )  (63.24%)
   145,925,050,661      branches                         #  237.214 M/sec                       ( +-  0.04% )  (62.92%)
     1,697,100,092      branch-misses                    #    1.16% of all branches             ( +-  0.11% )  (62.91%)
   443,952,688,369      L1-dcache-loads                  #  721.683 M/sec                       ( +-  0.02% )  (62.92%)
    16,268,384,320      L1-dcache-load-misses            #    3.66% of all L1-dcache accesses   ( +-  0.04% )  (62.94%)
     2,016,933,928      LLC-loads                        #    3.279 M/sec                       ( +-  0.07% )  (50.44%)
     1,612,870,452      LLC-load-misses                  #   79.97% of all L1-icache accesses   ( +-  0.06% )  (50.68%)

           33.3666 +- 0.0930 seconds time elapsed  ( +-  0.28% )
EOF

:<<'EOF'
# SPEEDTEST RESULTS

>./mySplit.speedtest.bash 


--------------------------------------------------------------------

FILE COUNT/SIZE AND TIME TAKEN BY FIND COMMAND:

489946

real    0m0.902s
user    0m0.505s
sys     0m0.460s

TOTAL SIZE OF ALL FILES: 18164753116 (19G)



--------------------------------------------------------------------

STARTING TESTS FOR sha1sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha1sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
489946                  489946                  489946            
                                                                  
real    0m21.560s       real    0m3.943s        real    0m2.289s     
user    0m48.434s       user    0m23.641s       user    0m34.001s    
sys     0m11.009s       sys     0m7.020s        sys     0m8.560s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       941%    (841% slower than mySplit)
xargs:          172%    (72% slower than mySplit)
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
489946                  489946                  489946            
                                                                  
real    0m22.896s       real    0m6.548s        real    0m3.880s     
user    1m7.247s        user    0m52.323s       user    1m5.987s     
sys     0m10.685s       sys     0m6.953s        sys     0m8.629s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       590%    (490% slower than mySplit)
xargs:          168%    (68% slower than mySplit)
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
489946                  489946                  489946            
                                                                  
real    0m22.123s       real    0m4.425s        real    0m3.096s     
user    0m58.822s       user    0m39.179s       user    0m50.085s    
sys     0m10.757s       sys     0m6.973s        sys     0m8.588s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       714%    (614% slower than mySplit)
xargs:          142%    (42% slower than mySplit)
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
489946                  489946                  489946            
                                                                  
real    0m23.017s       real    0m6.432s        real    0m3.994s     
user    1m7.091s        user    0m52.890s       user    1m5.966s     
sys     0m10.646s       sys     0m6.889s        sys     0m8.626s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       576%    (476% slower than mySplit)
xargs:          161%    (61% slower than mySplit)
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
489946                  489946                  489946            
                                                                  
real    0m22.108s       real    0m4.485s        real    0m2.943s     
user    0m57.591s       user    0m37.409s       user    0m48.557s    
sys     0m10.656s       sys     0m6.935s        sys     0m8.564s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       751%    (651% slower than mySplit)
xargs:          152%    (52% slower than mySplit)
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
489946                  489946                  489946            
                                                                  
real    0m22.009s       real    0m4.367s        real    0m2.481s     
user    0m54.170s       user    0m28.074s       user    0m33.299s    
sys     0m10.793s       sys     0m7.058s        sys     0m8.574s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       887%    (787% slower than mySplit)
xargs:          176%    (76% slower than mySplit)
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
489946                  489946                  489946            
                                                                  
real    0m20.157s       real    0m2.840s        real    0m1.309s     
user    0m33.584s       user    0m7.784s        user    0m11.150s    
sys     0m10.804s       sys     0m7.778s        sys     0m8.708s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       1539%   (1439% slower than mySplit)
xargs:          216%    (116% slower than mySplit)
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
489946                  489946                  489946            
                                                                  
real    0m21.930s       real    0m4.359s        real    0m2.398s     
user    0m53.694s       user    0m27.681s       user    0m32.038s    
sys     0m10.639s       sys     0m6.669s        sys     0m7.906s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       914%    (814% slower than mySplit)
xargs:          181%    (81% slower than mySplit)
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
489946                  489946                  489946            
                                                                  
real    0m20.169s       real    0m3.324s        real    0m1.215s     
user    0m32.173s       user    0m6.940s        user    0m9.225s     
sys     0m11.087s       sys     0m8.367s        sys     0m9.131s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       1660%   (1560% slower than mySplit)
xargs:          273%    (173% slower than mySplit)
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
489946                  489946                  489946            
                                                                  
real    0m21.816s       real    0m4.177s        real    0m2.720s     
user    0m55.612s       user    0m33.948s       user    0m43.072s    
sys     0m10.538s       sys     0m6.734s        sys     0m8.139s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       802%    (702% slower than mySplit)
xargs:          153%    (53% slower than mySplit)
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
489946                  489946                  489946            
                                                                  
real    0m25.402s       real    0m12.021s       real    0m6.977s     
user    1m36.885s       user    1m40.708s       user    1m59.938s    
sys     0m10.920s       sys     0m7.379s        sys     0m8.926s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       364%    (264% slower than mySplit)
xargs:          172%    (72% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

TESTS COMPLETE!!!

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       941%            590%            714%            576%            751%            887%            1539%           914%            1660%           802%            364%            730%           
xargs:          172%            168%            142%            161%            152%            176%            216%            181%            273%            153%            172%            170%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           

OVERALL TIME TAKEN: 381 SECONDS
EOF
