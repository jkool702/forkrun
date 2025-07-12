# speedtest computing 13 different checksums on 680k files taking up 20 gb
# average file size is ~28 kb. Max file size is 32 mb.
# each speedtest is run twice - in one inputs are newline seperated, in the other they are NULL seperated
# lists containing filenames are pre-generated. These lists as well as the acrual files are all on a ramdisk (tmpfs)
# test was run on Fedora 41 (kernel 6.13.12-200.fc41.x86_64) on May 5th 2025
# system CPU is a 14-core/28-thread i9-7940x

# # # # # setup # # # # #

ff() {
sha1sum "${@}" >>/mnt/ramdisk/sum.sha1sum
sha256sum "${@}" >>/mnt/ramdisk/sum.sha256sum
sha512sum "${@}" >>/mnt/ramdisk/sum.sha512sum
sha224sum "${@}" >>/mnt/ramdisk/sum.sha224sum
sha384sum "${@}" >>/mnt/ramdisk/sum.sha384sum
md5sum "${@}" >>/mnt/ramdisk/sum.md5sum
sum -s "${@}" >>/mnt/ramdisk/sum.sum_s
sum -r "${@}" >>/mnt/ramdisk/sum.sum_r
cksum "${@}" >>/mnt/ramdisk/sum.cksum
b2sum "${@}" >>/mnt/ramdisk/sum.b2sum
cksum -a sm3 "${@}" >>/mnt/ramdisk/sum.cksum_a_sm3
xxhsum "${@}" >>/mnt/ramdisk/sum.xxhsum
xxhsum -H3 "${@}" >>/mnt/ramdisk/sum.xxhsum_H3
}

export -f ff



# # # # # forkrun # # # # #

# time { forkrun -z ff <../flist0; forkrun ff <../flist; cat /mnt/ramdisk/sum* | wc -l; }

17591444

real    0m47.447s
user    13m40.105s
sys     3m36.780s


# time { for nn in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3" xxhsum "xxhsum -H3"; do forkrun -z $nn </mnt/ramdisk/flist0; forkrun $nn </mnt/ramdisk/flist; done | wc -l; }
17591444

real    0m49.055s
user    13m7.490s
sys     3m16.714s


# # # # # xargs # # # # #


# time { for nn in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3" xxhsum "xxhsum -H3"; do xargs -P 28 -0 $nn </mnt/ramdisk/flist0; xargs -P 28 -d $'\n' $nn </mnt/ramdisk/flist; done |wc -l; }
17591444

real    0m59.565s
user    11m42.723s
sys     2m41.664s


# # # # # compare # # # # #

wall clock time:  xargs took ~17.7% more time --> forkrun is ~17.7% faster   ( 80.138 seconds vs 94.360 seconds )

total (user+sys) CPU time:  forkrun took ~9.3% more total CPU time --> xargs is ~9.3% more efficient    ( 1268.962 seconds vs 1160.493 seconds )

forkrun (on average) utilized 15.8 / 28 CPU cores 
xargs (on average) utilized 12.3 / 28 CPU cores 
