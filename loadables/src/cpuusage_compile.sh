# clone bash git repo, then cd to + move source .c files to bash/examples/loadables and then compile in that directory

# compile for x86_64
gcc -Wall -fPIC -flto -O3 -v -DSHELL -DLOADABLE_BUILTIN -I/usr/include -I/usr/include/bash -I/usr/include/bash/builtins -I/usr/include/bash/include -I. -c childusage.c -o childusage.o
gcc -shared -o childusage.so childusage.o
mv childusage.so childusage


gcc -Wall -fPIC -flto -O3 -v -DSHELL -DLOADABLE_BUILTIN -I/usr/include -I/usr/include/bash -I/usr/include/bash/builtins -I/usr/include/bash/include -I. -c cpuusage.c -o cpuusage.o
gcc -shared -o cpuusage.so cpuusage.o
mv cpuusage.so cpuusage



# cross-compile for aarch64
aarch64-linux-gnu-gcc --sysroot=/usr/aarch64-redhat-linux/sys-root/fc41/ -Wall -fPIC -flto -O3 -v -DSHELL -DLOADABLE_BUILTIN -I/usr/include -I/usr/include/bash -I/usr/include/bash/builtins -I/usr/include/bash/include -I. -I/usr/lib/gcc/aarch64-linux-gnu/14/include-fixed -I/usr/lib/gcc/aarch64-linux-gnu/14/include -c childusage.c -o childusage.o
aarch64-linux-gnu-gcc --sysroot=/usr/aarch64-redhat-linux/sys-root/fc41/  -shared -o childusage.so childusage.o
mv childusage.so childusage


aarch64-linux-gnu-gcc --sysroot=/usr/aarch64-redhat-linux/sys-root/fc41/ -Wall -fPIC -flto -O3 -v -DSHELL -DLOADABLE_BUILTIN -I/usr/include -I/usr/include/bash -I/usr/include/bash/builtins -I/usr/include/bash/include -I. -I/usr/lib/gcc/aarch64-linux-gnu/14/include-fixed -I/usr/lib/gcc/aarch64-linux-gnu/14/include -c cpuusage.c -o cpuusage.o
aarch64-linux-gnu-gcc --sysroot=/usr/aarch64-redhat-linux/sys-root/fc41/  -shared -o cpuusage.so cpuusage.o
mv cpuusage.so cpuusage

