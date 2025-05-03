# speedtest computing 13 different checksums on 680k files taking up 20 gb
# average file size is ~28 kb. Max file size is 32 mb.
# each speedtest is run twice - in one inputs are newline seperated, in the other they are NULL seperated
# lists containing filenames are pre-generated. These lists as well as the acrual files are all on a ramdisk (tmpfs)
# test was run on Fedora 41 (kernel 6.13.12-200.fc41.x86_64) on May 5th 2025
# system CPU is a 28-core i9-7940x


# # # # # forkrun # # # # #

# time { for nn in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3" xxhsum "xxhsum -H3"; do forkrun -z $nn <filelist0; forkrun $nn <filelist; done |wc -l; }

17680286

real    1m20.138s
user    18m4.482s
sys     3m50.480s


# # # # # xargs # # # # #


# time { for nn in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum  "sum -s" "sum -r" cksum b2sum "cksum -a sm3" xxhsum "xxhsum -H3"; do xargs -P 28 -0 $nn <filelist0; xargs -P 28 -d $'\n' $nn <filelist; done |wc -l; }

17680286

real    1m34.360s
user    16m9.415s
sys     3m11.078s


# # # # # compare # # # # #

wall clock time:  xargs took ~17.7% more time --> forkrun is ~17.7% faster   ( 80.138 seconds vs 94.360 seconds )

total (user+sys) CPU time:  forkrun took ~9.3% more total CPU time --> xargs is ~9.3% more efficient    ( 1268.962 seconds vs 1160.493 seconds )

forkrun (on average) utilized 15.8 / 28 CPU cores 
xargs (on average) utilized 12.3 / 28 CPU cores 
