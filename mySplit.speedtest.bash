# RESULTS SUMMARY - RELATIVE TIME TAKEN:
# (checksum type)      (xargs/mysplit)     (mysplit/xargs)
# sha1sum              134.79%             74.18%
# sha256sum            128.14%             78.03%
# sha512sum            126.31%             79.16%
# sha224sum            134.79%             74.18%
# sha384sum            128.22%             77.98%
# md5sum               150.11%             66.61%
# cksum (crc)          169.87%             58.86%
# b2sum                131.35%             76.13%
# xargs failed to run for 'sum -s', 'sum -r' and 'cksum -a sm3'

# SPEEDTEST CODE

# source mySplit
source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/mySplit.bash)

# copy /usr onto ramdisk
mkdir -p /mnt/ramdisk2
mount -t tmpfs tmpfs /mnt/ramdisk
mkdir /mnt/ramdisk2
sudo rsync -a /usr/* /mnt/ramdisk2/usr
sudo chown -R $USER:$USER /mnt/ramdisk2/usr

sleep 0.5s
time { find /mnt/ramdisk2/usr -type f  | wc -l; }

# run tests
for nfun in sha1sum sha256sum sha512sum sha224sum sha384sum md5sum 'sum -s' 'sum -r' cksum b2sum 'cksum -a sm3'; do
printf '\n\n---------------------------------------------------------\n%s\n\n----------------\nxargs:\n' "$nfun" 
time { find /mnt/ramdisk2/usr -type f | xargs -P $(nproc) -d $'\n' "${nfun}" 2>/dev/null | wc -l; }
printf '\n----------------\nmySplit:\n'
sleep 0.5s
time { find /mnt/ramdisk2/usr -type f | mySplit "${nfun}" 2>/dev/null | wc -l; }
sleep 0.5s
done

# RESULTS

:<<'EOF'

474705

real    0m0.759s
user    0m0.334s
sys     0m0.480s

---------------------------------------------------------
sha1sum

----------------
xargs:
474705

real    0m3.409s
user    0m23.566s
sys     0m7.296s

----------------
mySplit:
474705

real    0m2.529s
user    0m33.272s
sys     0m13.703s


---------------------------------------------------------
sha256sum

----------------
xargs:
474705

real    0m5.464s
user    0m51.942s
sys     0m7.304s

----------------
mySplit:
474705

real    0m4.264s
user    1m4.625s
sys     0m14.556s


---------------------------------------------------------
sha512sum

----------------
xargs:
474705

real    0m4.229s
user    0m38.098s
sys     0m7.209s

----------------
mySplit:
474705

real    0m3.348s
user    0m48.866s
sys     0m14.288s


---------------------------------------------------------
sha224sum

----------------
xargs:
474705

real    0m5.695s
user    0m52.103s
sys     0m7.295s

----------------
mySplit:
474705

real    0m4.225s
user    1m4.162s
sys     0m14.686s


---------------------------------------------------------
sha384sum

----------------
xargs:
474705

real    0m4.157s
user    0m36.977s
sys     0m7.322s

----------------
mySplit:
474705

real    0m3.242s
user    0m47.941s
sys     0m14.002s


---------------------------------------------------------
md5sum

----------------
xargs:
474705

real    0m4.026s
user    0m27.683s
sys     0m7.256s

----------------
mySplit:
474705

real    0m2.682s
user    0m33.248s
sys     0m13.984s


---------------------------------------------------------
sum -s

----------------
xargs:
0

real    0m0.046s
user    0m0.007s
sys     0m0.066s

----------------
mySplit:
474705

real    0m1.311s
user    0m10.241s
sys     0m13.248s


---------------------------------------------------------
sum -r

----------------
xargs:
0

real    0m0.043s
user    0m0.010s
sys     0m0.058s

----------------
mySplit:
474705

real    0m2.633s
user    0m31.834s
sys     0m13.348s


---------------------------------------------------------
cksum

----------------
xargs:
474705

real    0m2.098s
user    0m4.316s
sys     0m7.731s

----------------
mySplit:
474705

real    0m1.235s
user    0m8.261s
sys     0m13.552s


---------------------------------------------------------
b2sum

----------------
xargs:
474705

real    0m3.888s
user    0m31.664s
sys     0m7.094s

----------------
mySplit:
474705

real    0m2.960s
user    0m41.943s
sys     0m13.708s


---------------------------------------------------------
cksum -a sm3

----------------
xargs:
0

real    0m0.045s
user    0m0.009s
sys     0m0.064s

----------------
mySplit:
474705

real    0m7.146s
user    1m58.474s
sys     0m16.333s

EOF
