# This contains the forkrun-accelerated scripts for the 
# NOAA weather data (max temperature 2015-2019) problem in
# PaSh: Light-touch Data-Parallel Shell Processing

# NOTE: the script was updated to grab the NOAA data from 
#       https://www.ncei.noaa.gov/pub/data/noaa/

# Prerequisites: forkrun (https://github.com/jkool702/forkrun), 
# curl, gunzip, grep, sed, sort, cut, standard GNU coreutils

# Script 1: Combined Pipeline (Minimal storage footprint, 4m 50s)**

# wget https://raw.githubusercontent.com/jkool702/forkrun/main/frun.bash
source frun.bash

tmpdir="$(mktemp -d)"
cd "$tmpdir"

ff() {
    y="$1"
    shift 1
    curl --parallel $(printf '%s\n' "$@" | sed -E 's/^(.*)$/ -o \1 https:\/\/www.ncei.noaa.gov\/pub\/data\/noaa\/'"$y"'\/\1'/) 2>/dev/null
    for nn in "$@"; do
        gunzip -c "$nn" 2>/dev/null | cut -c 89-92 | grep -iv 999
        \rm -f "$nn"
    done | grep -E '.+' | sort -rn | head -n 1
}


time {
    for y in {2015..2019}; do
        curl --list-only https://www.ncei.noaa.gov/pub/data/noaa/$y/ 2>/dev/null | \
        grep -E 'href=.*.gz' | sed -E 's/^[^"]*"//; s/".*$//;' | \
        frun ff $y | grep -E '.+' | sort -rn | head -n 1 | \
        sed "s/^/Maximum temperature for $y is: /" >&$fd1 &
    done
    wait
} {fd1}>&1

# real    4m50.879s
# user    34m22.304s
# sys     10m3.586s


# Script 2: Split Pipeline (Max I/O isolation, 3m 17s fetch + 1m 35s compute)

# wget https://raw.githubusercontent.com/jkool702/forkrun/main/frun.bash
source frun.bash

tmpdir="$(mktemp -d)"
cd "$tmpdir"

ff1() {
    y="$1"                   
    shift 1                                                                                                                                                                                                                                 
    curl --parallel $(printf '%s\n' "$@" | sed -E 's/^(.*)$/ -o \1 https:\/\/www.ncei.noaa.gov\/pub\/data\/noaa\/'"$y"'\/\1'/) 2>/dev/null
}
ff2() {
    for nn in "$@"; do
        gunzip -c "$nn" 2>/dev/null | cut -c 89-92 | grep -iv 999
        \rm -f "$nn"
    done | grep -E '.+' | sort -rn | head -n 1
}


# Phase 1: Fetch
time {
    for y in {2015..2019}; do
        curl --list-only https://www.ncei.noaa.gov/pub/data/noaa/$y/ 2>/dev/null | \
        grep -E 'href=.*.gz' | sed -E 's/^[^"]*"//; s/".*$//;' | frun ff1 $y &
    done
    wait
}

# real    3m17.633s
# user    10m17.285s
# sys     5m24.321s


# Phase 2: Compute
time {
    for y in {2015..2019}; do
        printf '%s\n' *-${y}.gz | frun ff2 $y | grep -E '.+' | sort -rn | head -n 1 | \
        sed "s/^/Maximum temperature for $y is: /" >&$fd1 &
    done
    wait
} {fd1}>&1

# real    1m35.751s
# user    29m52.698s
# sys     7m22.533s

