git clone https://git.savannah.gnu.org/git/bash.git

cd bash

./configure

make -j$(nproc)
make -j$(nproc) all

cd examples/loadables

curl -o ./lseek.c 'https://raw.githubusercontent.com/jkool702/forkrun/main/lseek_builtin/lseek.c'

gcc -v -fPIC -DHAVE_CONFIG_H -DSHELL -DLOADABLE_BUILTIN -DSELECT_COMMAND -DUSING_BASH_MALLOC -g -O3 -Wno-parentheses -Wno-format-security -I. -I.. -I../.. -I../../lib -I../../builtins -I. -I../../include -I../../lib/malloc -I/mnt/ramdisk/bash -I/mnt/ramdisk/bash/lib -I/mnt/ramdisk/bash/builtins -L ../../lib/malloc -L ../.. -L /usr/lib/bash -I/usr/include/bash -I/usr/include/bash/builtins -I/usr/include/bash/include -c -o lseek.o lseek.c;
gcc -v -DSELECT_COMMAND -DLOADABLE_BUILTIN -DHAVE_CONFIG_H -DSHELL -DUSING_BASH_MALLOC -shared -Wl,-soname,lseek -L ../../lib/malloc -L ../.. -L /usr/lib/bash -O3 -o lseek lseek.o; 

mkdir -p /usr/local/lib/bash
cp lseek /usr/local/lib/bash

enable lseek
