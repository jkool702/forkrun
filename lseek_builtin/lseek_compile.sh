git clone https://git.savannah.gnu.org/git/bash.git

cd bash

./configure

make -j$(nproc)
make -j$(nproc) all

cd examples/loadables

curl -o ./lseek.c 'https://raw.githubusercontent.com/jkool702/forkrun/main/lseek_builtin/lseek.c'

gcc -v -fPIC -flto -DHAVE_CONFIG_H -DSHELL -DLOADABLE_BUILTIN -DSELECT_COMMAND -O3 -Wno-parentheses -Wno-format-security -I.  -I/usr/include/bash -I/usr/include/bash/builtins -I/usr/include/bash/include --shared -o lseek lseek.c;

mkdir -p /usr/local/lib/bash
cp lseek /usr/local/lib/bash

enable lseek
