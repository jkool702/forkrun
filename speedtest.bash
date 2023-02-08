########### TEST SETUP ###########

# copy '\usr' to a tmpfs
mkdir -p /mnt/ramdisk
mount -t tmpfs /mnt/ramdisk
rsync -a /usr/* /mnt/ramdisk/usr_copy
cd /mnt/ramdisk/usr_copy

# num files = 346844
find ./ -type f | wc -l
346844

# total size = ~ 15 G
du ./ -d 0
15649948        ./


########### PARALLEL ###########

time find ./ -type f | parallel -j28 -m -- sha256sum 2>/dev/null | wc -l

346845

real    0m9.624s
user    0m39.662s
sys     0m7.545s

# Took ~2.5x as long as forkrun

########### XARGS ###########

time find ./ -type f -print0 | xargs -P28 -0 -- sha256sum 2>/dev/null | wc -l

346845

real    0m6.220s
user    0m41.730s
sys     0m5.629s

# took ~1.6x as long as forkrun


########### FORKRUN ###########

time find ./ -type f | forkrun -l512 -- sha256sum 2>/dev/null | wc -l

346845

real    0m3.843s
user    0m49.641s
sys     0m7.286s

# with output ordering
time find ./ -type f | forkrun -l512 -k -- sha256sum 2>/dev/null | wc -l

346845

real    0m4.113s
user    0m52.070s
sys     0m8.441s



########### MACHINE STATS ###########

OS: Fedora Linux 36 (Thirty Six) x86_64 
Kernel: 6.1.9-100.fc36.x86_64 
Shell: bash 5.2.15 
CPU: Intel i9-7940X (14C/28T) @ 4.400GHz 
GPU: NVIDIA GeForce GTX 1080 Ti 
Memory: 128513MiB 

