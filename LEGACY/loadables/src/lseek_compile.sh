#!/usr/bin/env bash

cd /mnt/ramdisk

git clone https://git.savannah.gnu.org/git/bash.git
git clone https://github.com/ClickHouse/sysroot.git

cd bash

./configure

make -j$(nproc)
make -j$(nproc) all

cd examples/loadables

curl -o ./lseek.c 'https://raw.githubusercontent.com/jkool702/forkrun/main/lseek_builtin/lseek.c'

gcc -v -fPIC -flto -DHAVE_CONFIG_H -DSHELL -DLOADABLE_BUILTIN -DSELECT_COMMAND -O3 -Wno-parentheses -Wno-format-security -I. -I /usr/include -I/usr/include/bash -I/usr/include/bash/builtins -I/usr/include/bash/include --shared -o lseek lseek.c;

mkdir -p /usr/local/lib/bash/lseek
mv lseek /usr/local/lib/bash/lseek_all_arch/lseek.x86_64


aarch64-linux-gnu-gcc --sysroot=/usr/aarch64-redhat-linux/sys-root/fc41/ -v -fPIC -flto -static -DHAVE_CONFIG_H -DSHELL -DLOADABLE_BUILTIN -DSELECT_COMMAND -O3 -I. -I /usr/include -I/usr/include/bash -I/usr/include/bash/builtins -I/usr/include/bash/include -I /usr/lib/gcc/aarch64-linux-gnu/14/include-fixed -I /usr/lib/gcc/aarch64-linux-gnu/14/include --shared -o lseek lseek.c
mv lseek  /usr/local/lib/bash/lseek_all_arch/lseek.aarch64


riscv64-linux-gnu-gcc --sysroot=/mnt/ramdisk/sysroot/linux-riscv64 -v -fPIC -flto -static -DHAVE_CONFIG_H -DSHELL -DLOADABLE_BUILTIN -DSELECT_COMMAND -O3 -I. -I /usr/include -I/usr/include/bash -I/usr/include/bash/builtins -I/usr/include/bash/include -I /usr/lib/gcc/riscv64-linux-gnu/14/include-fixed -I /usr/lib/gcc/riscv64-linux-gnu/14/include --shared -o lseek lseek.c
mv lseek  /usr/local/lib/bash/lseek_all_arch/lseek.riscv64
chmod +x /usr/local/lib/bash/lseek_all_arch/lseek.riscv64

ln -s lseek_all_arch/lseek.x86_64 /usr/local/lib/bash/lseek

enable lseek
