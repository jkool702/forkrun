#!/usr/bin/env bash 

# TL;DR SUMMARY 
# 11 tests were run on `parallel -m`, `xargs -P $(nproc) -d $'\n'`, and `mySplit`. AFAIK, these are the fastest parallelization methods supported by `parallel` and `xargs`, respectively.
# These tests computed checksums of all files under /usr (including /lib, /lib64, /bin, /sbin, ...) using 11 different checksumming algorithms. 
# Files were first copied onto a tmpfs ramdisk to ensure disk I/O did not skew results. Machine has enough RAM to ensure nothing was swapped out. 
#
# The speedtest was run on a machine with an i9-7940x (14c/28t) CPU + 128 GB RAM running on Fedora 39 with kernel 6.5.11 at a "nice level" of -20 (highest priority)
# 
# Overall results were:
# ---> on average (looking at total time between all tests), mySplit was around twice as fast `xargs -P $(nproc) -d $'\n'` and around four tiumes as fast as `parallel -m`
# ---> in all tests mySplit was between 1.82x - 2.35x faster than `xargs -P $(nproc) -d $'\n'` and between 2.23x - 9.13x faster than `parallel -m`
#
# NOTE: though not shown here, when restricted to processing 1 line at a time (`parallel` ; `xargs -P $(nproc) -d $'\n' -L 1` ; `mySplit -l 1`), the performance gap is even larger:
#       mySplit tends to be at least 3-4x as fast as `xargs -P $(nproc) -d $'\n' -L 1` and >10x as fast as `parallel`

: <<'EOF'
TEST: 11 different checksums on ~496k files with a total size of ~19 GB

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       529%            344%            399%            322%            401%            534%            842%            493%            913%            449%            223%            409%           
xargs:          198%            196%            182%            185%            184%            235%            195%            213%            208%            192%            187%            194%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           

OVERALL TIME TAKEN: 287 SECONDS
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
findDirDefault='/mnt/ramdisk'

# value: true/false 
# decide whether to copy everything over to a tmpfs mounted at /mnt/ramdisk and run checks on those copies
# a tmpfs will be automatically mounted at /mnt/ramdisk (unless a tmpfs is already mounted there) and files will be copied to /mnt/ramdisk/${findDir} using `rsync a`
ramdiskTransferFlag=false

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

496132

real    0m0.742s
user    0m0.340s
sys     0m0.451s

TOTAL SIZE OF ALL FILES: 19039242924 (19G)



--------------------------------------------------------------------

STARTING TESTS FOR sha1sum
----------------------------

Testing parallel......done
Testing xargs.........done
Testing mySplit.......done


RESULTS FOR sha1sum
---------------------

-----parallel-----      ------xargs-------      -----mySplit------
496132                  496132                  496132            
                                                                  
real    0m11.580s       real    0m4.331s        real    0m2.186s     
user    0m35.006s       user    0m23.736s       user    0m35.124s    
sys     0m10.936s       sys     0m7.489s        sys     0m9.193s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       529%    (429% slower than mySplit)
xargs:          198%    (98% slower than mySplit)
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
496132                  496132                  496132            
                                                                  
real    0m12.887s       real    0m7.378s        real    0m3.746s     
user    0m54.450s       user    0m53.746s       user    1m9.437s     
sys     0m10.581s       sys     0m7.454s        sys     0m9.397s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       344%    (244% slower than mySplit)
xargs:          196%    (96% slower than mySplit)
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
496132                  496132                  496132            
                                                                  
real    0m12.252s       real    0m5.603s        real    0m3.065s     
user    0m43.895s       user    0m39.134s       user    0m51.293s    
sys     0m10.665s       sys     0m7.417s        sys     0m9.131s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       399%    (299% slower than mySplit)
xargs:          182%    (82% slower than mySplit)
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
496132                  496132                  496132            
                                                                  
real    0m13.016s       real    0m7.511s        real    0m4.040s     
user    0m54.565s       user    0m53.198s       user    1m8.013s     
sys     0m10.669s       sys     0m7.659s        sys     0m9.489s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       322%    (222% slower than mySplit)
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
496132                  496132                  496132            
                                                                  
real    0m12.441s       real    0m5.710s        real    0m3.097s     
user    0m43.585s       user    0m38.179s       user    0m50.946s    
sys     0m10.890s       sys     0m7.422s        sys     0m9.228s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       401%    (301% slower than mySplit)
xargs:          184%    (84% slower than mySplit)
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
496132                  496132                  496132            
                                                                  
real    0m12.117s       real    0m5.334s        real    0m2.268s     
user    0m42.003s       user    0m28.462s       user    0m34.789s    
sys     0m10.752s       sys     0m7.533s        sys     0m9.228s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       534%    (434% slower than mySplit)
xargs:          235%    (135% slower than mySplit)
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
496132                  496132                  496132            
                                                                  
real    0m10.172s       real    0m2.354s        real    0m1.207s     
user    0m20.606s       user    0m6.468s        user    0m10.942s    
sys     0m10.860s       sys     0m7.944s        sys     0m8.930s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       842%    (742% slower than mySplit)
xargs:          195%    (95% slower than mySplit)
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
496132                  496132                  496132            
                                                                  
real    0m12.110s       real    0m5.244s        real    0m2.455s     
user    0m42.128s       user    0m28.203s       user    0m33.128s    
sys     0m10.788s       sys     0m7.293s        sys     0m8.424s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       493%    (393% slower than mySplit)
xargs:          213%    (113% slower than mySplit)
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
496132                  496132                  496132            
                                                                  
real    0m10.269s       real    0m2.345s        real    0m1.124s     
user    0m19.123s       user    0m4.930s        user    0m8.825s     
sys     0m11.431s       sys     0m8.297s        sys     0m9.426s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       913%    (813% slower than mySplit)
xargs:          208%    (108% slower than mySplit)
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
496132                  496132                  496132            
                                                                  
real    0m11.863s       real    0m5.068s        real    0m2.637s     
user    0m40.744s       user    0m33.379s       user    0m43.471s    
sys     0m10.412s       sys     0m7.312s        sys     0m8.656s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       449%    (349% slower than mySplit)
xargs:          192%    (92% slower than mySplit)
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
496132                  496132                  496132            
                                                                  
real    0m15.617s       real    0m13.097s       real    0m6.989s     
user    1m26.295s       user    1m43.173s       user    2m6.733s     
sys     0m10.557s       sys     0m7.986s        sys     0m9.783s      


RELATIVE WALL-CLOCK TIME TAKEN
------------------------------

parallel:       223%    (123% slower than mySplit)
xargs:          187%    (87% slower than mySplit)
mySplit:        100%


--------------------------------------------------------------------

TESTS COMPLETE!!!

OVERALL RELATIVE WALL-CLOCK TIME RESULTS SUMMARY:

                sha1sum         sha256sum       sha512sum       sha224sum       sha384sum       md5sum          sum -s          sum -r          cksum           b2sum           cksum -a sm3    OVERALL AVERAGE

parallel:       529%            344%            399%            322%            401%            534%            842%            493%            913%            449%            223%            409%           
xargs:          198%            196%            182%            185%            184%            235%            195%            213%            208%            192%            187%            194%           
mySplit:        100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%            100%           

OVERALL TIME TAKEN: 287 SECONDS
EOF
