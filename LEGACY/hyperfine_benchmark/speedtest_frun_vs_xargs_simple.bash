# speedtest computing 13 different checksums on 680k files taking up 20 gb
# average file size is ~28 kb. Max file size is 32 mb.
# each speedtest is run twice - in one inputs are newline seperated, in the other they are NULL seperated
# lists containing filenames are pre-generated. These lists as well as the acrual files are all on a ramdisk (tmpfs)
# test was run on Fedora 41 (kernel 6.13.12-200.fc41.x86_64) on May 5th 2025
# system CPU is a 14-core/28-thread i9-7940x

# # # # # setup # # # # #

[[ -d /mnt/ramdisk/usr ]] || {
mkdir -p /mnt/ramdisk
mount | grep -qE '^tmpfs on /mnt/ramdisk ' || sudo mount -t tmpfs tmpfs /mnt/ramdisk 
mkdir -p /mnt/ramdisk/usr
rsync -a --max-size=$((1<<22)) /usr/* /mnt/ramdisk/usr
find /mnt/ramdisk/usr -type f >/mnt/ramdisk/flist
find /mnt/ramdisk/usr -type f -print0 >/mnt/ramdisk/flist0
}

ff() {
sha1sum "${@}" 
sha256sum "${@}" 
sha512sum "${@}" 
sha224sum "${@}" 
sha384sum "${@}" 
md5sum "${@}" 
sum -s "${@}" 
sum -r "${@}" 
cksum "${@}" 
b2sum "${@}" 
cksum -a sm3 "${@}" 
xxhsum "${@}" 
xxhsum -H3 "${@}" 
}
export -f ff



time { frun ff </mnt/ramdisk/flist | wc -l; }
9570002

real    0m22.126s
user    5m37.261s
sys     1m20.350s



time { for nn in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3" xxhsum "xxhsum -H3"; do  xargs -P $(nproc) -d $'\n' $nn </mnt/ramdisk/flist; done | wc -l; }
9570002

real    0m21.556s
user    4m39.684s
sys     1m7.753s


# # # # # forkrun # # # # #

time { { frun -d '' ff </mnt/ramdisk/flist0; frun ff </mnt/ramdisk/flist; } | wc -l; }
: <<'EOF1'
17591444

real    0m47.447s
user    13m40.105s
sys     3m36.780s
EOF1

time { for nn in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3" xxhsum "xxhsum -H3"; do frun -d '' $nn </mnt/ramdisk/flist0; frun $nn </mnt/ramdisk/flist; done | wc -l; }
: <<'EOF2'
17591444

real    0m49.055s
user    13m7.490s
sys     3m16.714s
EOF2

# # # # # xargs # # # # #


time { for nn in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3" xxhsum "xxhsum -H3"; do xargs -P $(nproc) -0 $nn </mnt/ramdisk/flist0; xargs -P $(nproc) -d $'\n' $nn </mnt/ramdisk/flist; done | wc -l; }
: <<'EOF3'
17591444

real    0m59.565s
user    11m42.723s
sys     2m41.664s
EOF3

# # # # # compare # # # # #
: <<'EOF4'
wall clock time:  xargs took ~17.7% more time --> forkrun is ~17.7% faster   ( 80.138 seconds vs 94.360 seconds )

total (user+sys) CPU time:  forkrun took ~9.3% more total CPU time --> xargs is ~9.3% more efficient    ( 1268.962 seconds vs 1160.493 seconds )

forkrun (on average) utilized 15.8 / 28 CPU cores 
xargs (on average) utilized 12.3 / 28 CPU cores 
EOF4
