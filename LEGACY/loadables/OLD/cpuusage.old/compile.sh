gcc -Wall -fPIC -c cpuusage.c -o cpuusage.o
gcc -shared -o cpuusage.so cpuusage.o


gcc -Wall -fPIC -c childusage.c -o childusage.o
gcc -shared -o childusage.so childusage.o




# usage
: >>EOF

childusage:
In each worker coprocess, call the childusage builtin (with a unique ID as an argument) after each iteration. This will call getrusage(RUSAGE_CHILDREN), convert the time to clock ticks, and write the value to a file in ${tmpDir}/.cpuusage/cpu.<ID>. The value is also printed.

cpuusage:
When you run the cpuusage builtin with one or more worker coprocess PIDs, it will:

Scan the persistent directory (${tmpDir}/.cpuusage/) to sum finished CPU times from all files.
Recursively scan /proc to sum live CPU times (using different sums for worker coprocesses and their descendants).
Read the overall system CPU time from /proc/stat.
Print two numbers: the total CPU_LOAD_TIME (live plus persistent finished CPU time) and the total CPU_ALL_TIME.
EOF