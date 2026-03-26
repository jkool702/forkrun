```
-------------------------------- 1024 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      72.6 ms ±   0.4 ms    [User: 90.8 ms, System: 38.2 ms]
  Range (min … max):    72.0 ms …  73.8 ms    39 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      72.1 ms ±   0.5 ms    [User: 93.1 ms, System: 42.6 ms]
  Range (min … max):    71.5 ms …  73.4 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      78.8 ms ±   0.4 ms    [User: 65.1 ms, System: 13.4 ms]
  Range (min … max):    77.8 ms …  79.8 ms    36 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     198.0 ms ±   1.1 ms    [User: 214.5 ms, System: 142.7 ms]
  Range (min … max):   195.9 ms … 200.5 ms    14 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.09 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    2.75 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     117.6 ms ±   1.0 ms    [User: 158.2 ms, System: 39.0 ms]
  Range (min … max):   116.7 ms … 121.7 ms    24 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     116.8 ms ±   0.6 ms    [User: 159.0 ms, System: 44.6 ms]
  Range (min … max):   116.0 ms … 118.3 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
 
  Warning: The first benchmarking run for this command was significantly slower than the rest (150.8 ms). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
  Time (mean ± σ):     145.7 ms ±   1.3 ms    [User: 130.3 ms, System: 15.0 ms]
  Range (min … max):   144.7 ms … 150.8 ms    19 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     263.9 ms ±   3.2 ms    [User: 279.8 ms, System: 146.8 ms]
  Range (min … max):   261.7 ms … 273.2 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.25 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    2.26 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      91.1 ms ±   1.0 ms    [User: 119.5 ms, System: 39.0 ms]
  Range (min … max):    90.0 ms …  94.0 ms    31 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      90.0 ms ±   0.4 ms    [User: 121.6 ms, System: 43.2 ms]
  Range (min … max):    89.3 ms …  90.8 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     107.4 ms ±   0.6 ms    [User: 92.7 ms, System: 14.4 ms]
  Range (min … max):   106.5 ms … 109.2 ms    26 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     225.1 ms ±   2.2 ms    [User: 240.6 ms, System: 145.8 ms]
  Range (min … max):   222.6 ms … 231.7 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.19 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    2.50 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     117.6 ms ±   0.6 ms    [User: 158.7 ms, System: 38.0 ms]
  Range (min … max):   116.8 ms … 118.7 ms    24 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     116.6 ms ±   0.8 ms    [User: 162.6 ms, System: 40.9 ms]
  Range (min … max):   115.5 ms … 119.4 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     145.6 ms ±   0.7 ms    [User: 131.8 ms, System: 13.5 ms]
  Range (min … max):   144.4 ms … 148.0 ms    20 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     262.4 ms ±   1.6 ms    [User: 281.3 ms, System: 145.1 ms]
  Range (min … max):   261.1 ms … 266.6 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.25 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    2.25 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      90.9 ms ±   1.1 ms    [User: 118.2 ms, System: 39.2 ms]
  Range (min … max):    89.7 ms …  95.0 ms    31 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      90.0 ms ±   0.5 ms    [User: 120.0 ms, System: 44.1 ms]
  Range (min … max):    89.1 ms …  91.5 ms    32 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     106.5 ms ±   0.4 ms    [User: 91.2 ms, System: 15.0 ms]
  Range (min … max):   106.0 ms … 107.3 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     224.8 ms ±   0.6 ms    [User: 236.9 ms, System: 149.3 ms]
  Range (min … max):   223.7 ms … 225.7 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.18 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    2.50 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      88.6 ms ±   0.5 ms    [User: 113.7 ms, System: 39.0 ms]
  Range (min … max):    87.9 ms …  89.9 ms    32 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      88.1 ms ±   0.6 ms    [User: 116.8 ms, System: 42.7 ms]
  Range (min … max):    87.2 ms …  90.0 ms    32 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     102.0 ms ±   0.6 ms    [User: 86.4 ms, System: 15.3 ms]
  Range (min … max):   101.1 ms … 104.0 ms    28 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     220.5 ms ±   0.8 ms    [User: 235.9 ms, System: 145.4 ms]
  Range (min … max):   219.1 ms … 221.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.00 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.16 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    2.50 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      37.7 ms ±   0.3 ms    [User: 38.5 ms, System: 37.2 ms]
  Range (min … max):    37.3 ms …  39.1 ms    72 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      37.0 ms ±   0.4 ms    [User: 40.7 ms, System: 38.9 ms]
  Range (min … max):    36.4 ms …  38.3 ms    71 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      28.9 ms ±   0.4 ms    [User: 15.4 ms, System: 13.5 ms]
  Range (min … max):    28.1 ms …  30.3 ms    90 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     174.7 ms ±   0.8 ms    [User: 162.5 ms, System: 134.4 ms]
  Range (min … max):   173.6 ms … 175.9 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.28 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.30 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    6.04 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      89.9 ms ±   0.5 ms    [User: 116.1 ms, System: 35.9 ms]
  Range (min … max):    88.6 ms …  91.1 ms    32 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      88.5 ms ±   0.5 ms    [User: 116.9 ms, System: 40.5 ms]
  Range (min … max):    87.7 ms …  90.0 ms    32 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     103.0 ms ±   0.4 ms    [User: 88.8 ms, System: 14.0 ms]
  Range (min … max):   102.1 ms … 103.8 ms    28 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     222.8 ms ±   1.4 ms    [User: 236.3 ms, System: 136.1 ms]
  Range (min … max):   220.8 ms … 226.2 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.02 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.16 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    2.52 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      35.1 ms ±   0.3 ms    [User: 35.2 ms, System: 38.3 ms]
  Range (min … max):    34.7 ms …  36.3 ms    76 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      35.2 ms ±   0.3 ms    [User: 38.0 ms, System: 42.5 ms]
  Range (min … max):    34.7 ms …  36.3 ms    76 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      24.7 ms ±   0.5 ms    [User: 10.7 ms, System: 13.9 ms]
  Range (min … max):    23.8 ms …  27.1 ms    104 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     174.4 ms ±   1.4 ms    [User: 157.0 ms, System: 146.3 ms]
  Range (min … max):   172.7 ms … 177.8 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.43 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.43 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    7.07 ± 0.15 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      83.2 ms ±   0.5 ms    [User: 106.8 ms, System: 37.3 ms]
  Range (min … max):    82.4 ms …  84.7 ms    34 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      82.1 ms ±   0.5 ms    [User: 108.1 ms, System: 41.2 ms]
  Range (min … max):    81.3 ms …  83.3 ms    35 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):      95.2 ms ±   0.4 ms    [User: 80.7 ms, System: 14.3 ms]
  Range (min … max):    94.6 ms …  97.0 ms    30 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
 
  Warning: The first benchmarking run for this command was significantly slower than the rest (217.0 ms  Time (mean ± σ):     213.7 ms ±   1.0 ms    [User: 223.9 ms, System: 139.4 ms]
  Range (min … max):   213.0 ms … 217.0 ms    13 runs
). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.16 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    2.60 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     188.9 ms ±   0.7 ms    [User: 265.4 ms, System: 38.8 ms]
  Range (min … max):   188.3 ms … 190.5 ms    15 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     187.5 ms ±   1.7 ms    [User: 271.3 ms, System: 41.8 ms]
  Range (min … max):   186.1 ms … 193.2 ms    15 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1
  Time (mean ± σ):     251.5 ms ±   0.9 ms    [User: 237.0 ms, System: 14.0 ms]
  Range (min … max):   250.4 ms … 253.5 ms    11 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     364.5 ms ±   0.5 ms    [User: 384.2 ms, System: 150.0 ms]
  Range (min … max):   363.5 ms … 364.8 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.34 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1
    1.94 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1

-------------------------------- 4096 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      65.7 ms ±   0.8 ms    [User: 122.4 ms, System: 56.5 ms]
  Range (min … max):    63.9 ms …  67.6 ms    43 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      62.3 ms ±   1.2 ms    [User: 121.2 ms, System: 61.5 ms]
  Range (min … max):    59.2 ms …  65.4 ms    45 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      58.7 ms ±   0.4 ms    [User: 89.5 ms, System: 32.6 ms]
  Range (min … max):    58.0 ms …  60.4 ms    48 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     222.6 ms ±   1.0 ms    [User: 288.6 ms, System: 168.5 ms]
  Range (min … max):   220.8 ms … 224.1 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.12 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    3.79 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      96.4 ms ±   1.6 ms    [User: 205.9 ms, System: 57.4 ms]
  Range (min … max):    95.1 ms … 100.2 ms    30 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
 
    Time (mean ± σ):      90.2 ms ±   1.3 ms    [User: 206.7 ms, System: 60.2 ms]
  Range (min … max):    89.0 ms …  95.1 ms    32 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      97.4 ms ±   0.4 ms    [User: 172.1 ms, System: 32.7 ms]
  Range (min … max):    96.5 ms …  98.1 ms    29 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     229.6 ms ±   1.0 ms    [User: 375.0 ms, System: 167.8 ms]
  Range (min … max):   228.8 ms … 232.3 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.07 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.08 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    2.55 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
 
  Warning:   Time (mean ± σ):      79.6 ms ±   0.8 ms    [User: 162.9 ms, System: 58.0 ms]
  Range (min … max):    77.3 ms …  82.1 ms    35 runs
Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      75.3 ms ±   1.5 ms    [User: 164.7 ms, System: 60.5 ms]
  Range (min … max):    71.3 ms …  78.7 ms    38 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      77.3 ms ±   0.3 ms    [User: 130.1 ms, System: 33.0 ms]
  Range (min … max):    76.6 ms …  78.1 ms    36 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     223.0 ms ±   3.0 ms    [User: 334.3 ms, System: 166.2 ms]
  Range (min … max):   218.8 ms … 230.6 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    2.96 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      95.4 ms ±   1.0 ms    [User: 202.2 ms, System: 60.0 ms]
  Range (min … max):    93.1 ms …  98.3 ms    30 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      90.6 ms ±   1.9 ms    [User: 207.4 ms, System: 59.5 ms]
  Range (min … max):    88.8 ms …  95.1 ms    30 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      97.1 ms ±   0.7 ms    [User: 171.3 ms, System: 32.6 ms]
  Range (min … max):    96.2 ms …  99.5 ms    29 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     229.3 ms ±   0.5 ms    [User: 373.5 ms, System: 168.0 ms]
  Range (min … max):   228.4 ms … 230.1 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.05 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.07 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    2.53 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      79.2 ms ±   1.2 ms    [User: 157.7 ms, System: 59.9 ms]
  Range (min … max):    76.5 ms …  82.0 ms    36 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      74.4 ms ±   1.1 ms    [User: 159.6 ms, System: 61.7 ms]
  Range (min … max):    70.9 ms …  76.9 ms    38 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      76.0 ms ±   0.5 ms    [User: 127.9 ms, System: 32.1 ms]
  Range (min … max):    75.3 ms …  77.6 ms    37 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     224.3 ms ±   2.2 ms    [User: 327.5 ms, System: 171.2 ms]
  Range (min … max):   221.6 ms … 228.3 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.07 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    3.02 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
 
    Time (mean ± σ):      76.5 ms ±   1.4 ms    [User: 151.8 ms, System: 55.3 ms]
  Range (min … max):    74.0 ms …  81.0 ms    38 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      72.1 ms ±   1.2 ms    [User: 150.4 ms, System: 60.1 ms]
  Range (min … max):    69.7 ms …  75.6 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      72.0 ms ±   0.8 ms    [User: 117.0 ms, System: 32.8 ms]
  Range (min … max):    71.2 ms …  75.5 ms    39 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     222.5 ms ±   1.6 ms    [User: 319.3 ms, System: 165.2 ms]
  Range (min … max):   219.3 ms … 225.8 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.00 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    3.09 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      43.7 ms ±   0.4 ms    [User: 59.4 ms, System: 56.0 ms]
  Range (min … max):    42.6 ms …  45.0 ms    63 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      41.5 ms ±   0.8 ms    [User: 60.7 ms, System: 58.8 ms]
  Range (min … max):    40.5 ms …  43.4 ms    67 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      30.3 ms ±   0.3 ms    [User: 30.4 ms, System: 31.4 ms]
  Range (min … max):    29.7 ms …  31.4 ms    87 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     224.3 ms ±   2.3 ms    [User: 227.2 ms, System: 161.8 ms]
  Range (min … max):   222.1 ms … 230.6 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.37 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.44 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    7.40 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      76.5 ms ±   0.8 ms    [User: 148.9 ms, System: 56.0 ms]
  Range (min … max):    74.5 ms …  79.1 ms    37 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      72.9 ms ±   1.4 ms    [User: 153.6 ms, System: 55.2 ms]
  Range (min … max):    70.5 ms …  76.1 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      71.9 ms ±   0.3 ms    [User: 118.8 ms, System: 30.9 ms]
  Range (min … max):    71.2 ms …  72.9 ms    39 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     222.8 ms ±   1.7 ms    [User: 311.5 ms, System: 164.5 ms]
  Range (min … max):   219.4 ms … 225.6 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.06 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    3.10 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      41.2 ms ±   0.4 ms    [User: 52.6 ms, System: 57.2 ms]
  Range (min … max):    40.5 ms …  42.5 ms    66 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      39.3 ms ±   0.6 ms    [User: 53.5 ms, System: 60.1 ms]
  Range (min … max):    38.6 ms …  41.4 ms    69 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      26.8 ms ±   0.3 ms    [User: 22.5 ms, System: 31.5 ms]
  Range (min … max):    26.2 ms …  28.4 ms    97 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     224.7 ms ±   1.5 ms    [User: 220.9 ms, System: 170.9 ms]
  Range (min … max):   222.3 ms … 227.1 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.47 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.54 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    8.38 ± 0.12 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      74.7 ms ±   0.7 ms    [User: 147.0 ms, System: 56.1 ms]
  Range (min … max):    73.3 ms …  75.7 ms    38 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      70.8 ms ±   1.8 ms    [User: 148.3 ms, System: 58.3 ms]
  Range (min … max):    66.3 ms …  74.7 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):      70.2 ms ±   0.7 ms    [User: 115.4 ms, System: 31.9 ms]
  Range (min … max):    69.4 ms …  72.7 ms    40 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     222.4 ms ±   1.1 ms    [User: 312.8 ms, System: 160.6 ms]
  Range (min … max):   220.5 ms … 224.1 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.01 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.06 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    3.17 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2
 
  Warning  Time (mean ± σ):     143.1 ms ±   3.3 ms    [User: 337.0 ms, System: 56.6 ms]
  Range (min … max):   140.9 ms … 153.6 ms    20 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     133.6 ms ±   1.7 ms    [User: 336.4 ms, System: 61.1 ms]
  Range (min … max):   129.3 ms … 137.3 ms    21 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     157.0 ms ±   0.5 ms    [User: 301.0 ms, System: 31.1 ms]
  Range (min … max):   156.6 ms … 158.5 ms    18 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2
  Time (mean ± σ):     268.3 ms ±   0.7 ms    [User: 507.5 ms, System: 166.6 ms]
  Range (min … max):   267.1 ms … 269.0 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 ran
    1.07 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    1.18 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2
    2.01 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2

-------------------------------- 16384 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     186.7 ms ±   1.0 ms    [User: 819.3 ms, System: 219.6 ms]
  Range (min … max):   185.4 ms … 189.5 ms    15 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     196.9 ms ±  16.8 ms    [User: 940.4 ms, System: 236.8 ms]
  Range (min … max):   180.4 ms … 234.7 ms    16 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     238.7 ms ±   0.9 ms    [User: 747.7 ms, System: 167.2 ms]
  Range (min … max):   237.7 ms … 240.4 ms    12 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     471.5 ms ±   1.7 ms    [User: 1196.0 ms, System: 375.0 ms]
  Range (min … max):   469.4 ms … 475.2 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.05 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.28 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    2.53 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     332.2 ms ±   2.1 ms    [User: 1638.3 ms, System: 210.5 ms]
 
    Range (min … max):   330.2 ms … 336.5 ms    10 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     358.3 ms ±  29.3 ms    [User: 1825.3 ms, System: 227.1 ms]
  Range (min … max):   332.9 ms … 395.3 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     468.1 ms ±   2.0 ms    [User: 1548.5 ms, System: 171.7 ms]
  Range (min … max):   466.5 ms … 472.2 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     553.8 ms ±   4.4 ms    [User: 2027.7 ms, System: 374.4 ms]
  Range (min … max):   549.3 ms … 564.0 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.08 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.41 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.67 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     246.7 ms ±   1.7 ms    [User: 1180.5 ms, System: 223.5 ms]
  Range (min … max):   245.1 ms … 251.2 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     256.2 ms ±  16.6 ms    [User: 1325.2 ms, System: 233.8 ms]
  Range (min … max):   241.9 ms … 279.0 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     332.6 ms ±   1.6 ms    [User: 1095.2 ms, System: 171.9 ms]
  Range (min … max):   331.6 ms … 337.1 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     501.8 ms ±   2.1 ms    [User: 1561.7 ms, System: 374.8 ms]
  Range (min … max):   499.3 ms … 504.2 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.04 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.35 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    2.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     332.5 ms ±   1.9 ms    [User: 1629.6 ms, System: 216.3 ms]
  Range (min … max):   330.6 ms … 336.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     358.2 ms ±  26.3 ms    [User: 1824.1 ms, System: 226.7 ms]
  Range (min … max):   331.9 ms … 397.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
 
  Warning:   Time (mean ± σ):     468.6 ms ±   5.5 ms    [User: 1552.3 ms, System: 166.7 ms]
  Range (min … max):   466.3 ms … 484.2 ms    10 runs
Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     552.0 ms ±   1.6 ms    [User: 2026.1 ms, System: 369.2 ms]
  Range (min … max):   549.3 ms … 554.8 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.08 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.41 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.66 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     245.8 ms ±   2.2 ms    [User: 1165.5 ms, System: 215.9 ms]
  Range (min … max):   243.6 ms … 250.9 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     260.6 ms ±  17.6 ms    [User: 1309.0 ms, System: 233.3 ms]
  Range (min … max):   242.1 ms … 287.7 ms    12 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     329.9 ms ±   0.5 ms    [User: 1082.3 ms, System: 170.8 ms]
  Range (min … max):   329.2 ms … 330.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     502.6 ms ±   3.1 ms    [User: 1544.9 ms, System: 381.2 ms]
  Range (min … max):   497.6 ms … 509.7 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.06 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.34 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    2.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     235.7 ms ±   0.7 ms    [User: 1099.1 ms, System: 215.0 ms]
  Range (min … max):   235.0 ms … 237.2 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     235.5 ms ±   3.1 ms    [User: 1146.6 ms, System: 235.3 ms]
  Range (min … max):   232.7 ms … 242.1 ms    12 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     318.4 ms ±   0.3 ms    [User: 1020.6 ms, System: 171.9 ms]
  Range (min … max):   317.9 ms … 318.7 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     498.1 ms ±   3.9 ms    [User: 1486.3 ms, System: 370.5 ms]
  Range (min … max):   494.7 ms … 508.7 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.00 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.35 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    2.12 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3
 
    Time (mean ± σ):      80.8 ms ±   2.1 ms    [User: 227.1 ms, System: 215.8 ms]
  Range (min … max):    77.8 ms …  91.7 ms    35 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):      75.2 ms ±   3.7 ms    [User: 255.5 ms, System: 237.0 ms]
  Range (min … max):    71.8 ms …  87.9 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):      68.3 ms ±   0.3 ms    [User: 158.5 ms, System: 164.7 ms]
  Range (min … max):    67.7 ms …  69.0 ms    41 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     449.8 ms ±   3.4 ms    [User: 599.3 ms, System: 359.3 ms]
  Range (min … max):   446.2 ms … 455.6 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.10 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.18 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    6.59 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     238.5 ms ±   0.5 ms    [User: 1119.1 ms, System: 205.5 ms]
  Range (min … max):   237.9 ms … 239.5 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     242.3 ms ±   5.2 ms    [User: 1156.5 ms, System: 232.4 ms]
  Range (min … max):   236.6 ms … 249.0 ms    11 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     323.7 ms ±   0.6 ms    [User: 1043.2 ms, System: 162.8 ms]
  Range (min … max):   323.0 ms … 325.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     499.5 ms ±   2.4 ms    [User: 1495.8 ms, System: 359.8 ms]
  Range (min … max):   494.5 ms … 502.1 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.36 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    2.09 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
 
  Warning  Time (mean ± σ):      72.2 ms ±   2.2 ms    [User: 170.0 ms, System: 221.5 ms]
  Range (min … max):    68.6 ms …  79.9 ms    41 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):      66.8 ms ±   2.7 ms    [User: 189.7 ms, System: 247.3 ms]
  Range (min … max):    63.7 ms …  76.0 ms    43 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):      54.7 ms ±   0.4 ms    [User: 102.8 ms, System: 164.7 ms]
  Range (min … max):    54.2 ms …  55.9 ms    51 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     448.7 ms ±   2.5 ms    [User: 556.0 ms, System: 359.0 ms]
  Range (min … max):   445.0 ms … 453.2 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.22 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.32 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    8.20 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     221.9 ms ±   1.4 ms    [User: 1035.0 ms, System: 212.8 ms]
  Range (min … max):   220.1 ms … 225.7 ms    13 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     243.2 ms ±  17.3 ms    [User: 1178.8 ms, System: 226.3 ms]
  Range (min … max):   216.9 ms … 277.0 ms    12 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     291.8 ms ±   0.6 ms    [User: 955.0 ms, System: 167.7 ms]
  Range (min … max):   290.3 ms … 292.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     487.1 ms ±   1.8 ms    [User: 1412.2 ms, System: 355.7 ms]
  Range (min … max):   483.8 ms … 490.8 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.10 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.31 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    2.19 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     573.2 ms ±   3.0 ms    [User: 2923.2 ms, System: 207.3 ms]
  Range (min … max):   570.8 ms … 580.4 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     597.6 ms ±  34.2 ms    [User: 3217.3 ms, System: 232.1 ms]
  Range (min … max):   570.4 ms … 647.8 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     836.3 ms ±   9.5 ms    [User: 2833.5 ms, System: 167.3 ms]
  Range (min … max):   831.9 ms … 862.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3
  Time (mean ± σ):     771.5 ms ±   2.8 ms    [User: 3304.0 ms, System: 379.0 ms]
  Range (min … max):   769.0 ms … 778.6 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 ran
    1.04 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.35 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3
    1.46 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3

-------------------------------- 65536 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     316.6 ms ±   1.7 ms    [User: 2696.3 ms, System: 699.8 ms]
  Range (min … max):   314.0 ms … 319.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     308.2 ms ±  13.7 ms    [User: 4181.8 ms, System: 895.0 ms]
  Range (min … max):   281.1 ms … 323.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     289.3 ms ±   7.5 ms    [User: 3725.4 ms, System: 709.6 ms]
  Range (min … max):   279.9 ms … 298.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.371 s ±  0.019 s    [User: 3.835 s, System: 1.025 s]
  Range (min … max):    1.346 s …  1.408 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.07 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.09 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    4.74 ± 0.14 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     558.8 ms ±  13.6 ms    [User: 5351.6 ms, System: 709.9 ms]
  Range (min … max):   548.7 ms … 590.9 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     536.2 ms ±  17.3 ms    [User: 8426.0 ms, System: 872.1 ms]
  Range (min … max):   516.6 ms … 563.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     563.5 ms ±  12.2 ms    [User: 7939.8 ms, System: 713.9 ms]
  Range (min … max):   544.1 ms … 581.5 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.427 s ±  0.009 s    [User: 6.397 s, System: 1.032 s]
  Range (min … max):    1.409 s …  1.441 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.04 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.05 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    2.66 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     420.9 ms ±   1.8 ms    [User: 3835.6 ms, System: 716.9 ms]
  Range (min … max):   417.6 ms … 423.2 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     411.9 ms ±  20.6 ms    [User: 6232.1 ms, System: 872.3 ms]
  Range (min … max):   376.5 ms … 440.3 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     424.1 ms ±   8.7 ms    [User: 5692.7 ms, System: 723.5 ms]
  Range (min … max):   409.8 ms … 436.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.373 s ±  0.008 s    [User: 4.964 s, System: 1.038 s]
  Range (min … max):    1.359 s …  1.384 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.02 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.03 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    3.33 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     550.2 ms ±   3.2 ms    [User: 5227.0 ms, System: 709.6 ms]
  Range (min … max):   546.0 ms … 555.5 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     523.5 ms ±  22.9 ms    [User: 8424.9 ms, System: 850.2 ms]
  Range (min … max):   488.5 ms … 555.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     557.0 ms ±  17.6 ms    [User: 7890.7 ms, System: 705.4 ms]
  Range (min … max):   524.5 ms … 576.7 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.429 s ±  0.012 s    [User: 6.382 s, System: 1.043 s]
  Range (min … max):    1.412 s …  1.457 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.05 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.06 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    2.73 ± 0.12 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     415.8 ms ±   3.0 ms    [User: 3780.3 ms, System: 714.8 ms]
  Range (min … max):   410.3 ms … 420.3 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     398.3 ms ±  16.1 ms    [User: 6060.7 ms, System: 883.4 ms]
  Range (min … max):   384.5 ms … 425.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     420.2 ms ±  11.1 ms    [User: 5609.0 ms, System: 712.2 ms]
  Range (min … max):   408.1 ms … 446.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.373 s ±  0.007 s    [User: 4.921 s, System: 1.025 s]
  Range (min … max):    1.366 s …  1.388 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.04 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.06 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    3.45 ± 0.14 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     394.8 ms ±   1.6 ms    [User: 3512.0 ms, System: 718.0 ms]
  Range (min … max):   392.0 ms … 396.9 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     322.5 ms ±   7.6 ms    [User: 4185.5 ms, System: 885.7 ms]
  Range (min … max):   314.7 ms … 333.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     323.1 ms ±  10.9 ms    [User: 3853.7 ms, System: 733.1 ms]
  Range (min … max):   309.5 ms … 338.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.366 s ±  0.009 s    [User: 4.710 s, System: 1.015 s]
  Range (min … max):    1.356 s …  1.379 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.00 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.22 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    4.23 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     145.0 ms ±   1.1 ms    [User: 789.5 ms, System: 707.7 ms]
  Range (min … max):   143.2 ms … 146.9 ms    19 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     126.5 ms ±   2.7 ms    [User: 1005.8 ms, System: 893.0 ms]
  Range (min … max):   122.1 ms … 131.5 ms    23 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     111.2 ms ±   6.3 ms    [User: 666.5 ms, System: 680.1 ms]
  Range (min … max):   104.9 ms … 124.6 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.340 s ±  0.010 s    [User: 2.002 s, System: 0.965 s]
  Range (min … max):    1.325 s …  1.359 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.14 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.30 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4
   12.05 ± 0.69 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     399.4 ms ±   1.4 ms    [User: 3587.4 ms, System: 681.6 ms]
  Range (min … max):   397.4 ms … 401.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     321.1 ms ±   8.8 ms    [User: 4226.3 ms, System: 855.8 ms]
  Range (min … max):   310.6 ms … 339.0 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     328.5 ms ±   6.4 ms    [User: 3876.7 ms, System: 704.2 ms]
  Range (min … max):   317.1 ms … 339.1 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.370 s ±  0.016 s    [User: 4.738 s, System: 0.999 s]
  Range (min … max):    1.354 s …  1.412 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.02 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.24 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    4.27 ± 0.13 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     131.0 ms ±   1.7 ms    [User: 600.9 ms, System: 719.3 ms]
  Range (min … max):   128.0 ms … 134.3 ms    22 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     119.3 ms ±   2.5 ms    [User: 712.2 ms, System: 874.4 ms]
  Range (min … max):   114.2 ms … 124.2 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
 
  Warning  Time (mean ± σ):      98.7 ms ±   3.2 ms    [User: 409.7 ms, System: 637.3 ms]
  Range (min … max):    96.1 ms … 111.4 ms    29 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.330 s ±  0.009 s    [User: 1.808 s, System: 0.989 s]
  Range (min … max):    1.322 s …  1.353 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.21 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.33 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
   13.48 ± 0.45 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     379.4 ms ±   3.1 ms    [User: 3394.4 ms, System: 693.3 ms]
  Range (min … max):   376.0 ms … 384.3 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     349.3 ms ±  15.2 ms    [User: 5269.5 ms, System: 859.6 ms]
  Range (min … max):   330.8 ms … 372.5 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     371.8 ms ±  19.8 ms    [User: 4765.2 ms, System: 700.3 ms]
  Range (min … max):   327.3 ms … 394.9 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.364 s ±  0.019 s    [User: 4.517 s, System: 0.993 s]
  Range (min … max):    1.346 s …  1.412 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.06 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.09 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    3.91 ± 0.18 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     921.6 ms ±   4.6 ms    [User: 9265.3 ms, System: 689.6 ms]
  Range (min … max):   913.9 ms … 927.5 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     912.8 ms ±  37.0 ms    [User: 15575.8 ms, System: 884.9 ms]
  Range (min … max):   859.2 ms … 966.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):     974.0 ms ±  21.9 ms    [User: 15034.2 ms, System: 723.8 ms]
  Range (min … max):   927.7 ms … 1003.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4
  Time (mean ± σ):      1.556 s ±  0.008 s    [User: 10.460 s, System: 1.061 s]
  Range (min … max):    1.549 s …  1.572 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 ran
    1.01 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.07 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4
    1.70 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4

-------------------------------- 262144 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.169 s ±  0.005 s    [User: 11.878 s, System: 2.878 s]
  Range (min … max):    1.165 s …  1.181 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.114 s ±  0.017 s    [User: 19.534 s, System: 3.643 s]
  Range (min … max):    1.100 s …  1.146 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.068 s ±  0.018 s    [User: 18.424 s, System: 3.186 s]
  Range (min … max):    1.038 s …  1.101 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      5.192 s ±  0.058 s    [User: 16.073 s, System: 3.831 s]
  Range (min … max):    5.135 s …  5.331 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.09 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    4.86 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      2.076 s ±  0.006 s    [User: 23.304 s, System: 2.854 s]
  Range (min … max):    2.067 s …  2.085 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      2.175 s ±  0.018 s    [User: 40.416 s, System: 3.515 s]
  Range (min … max):    2.154 s …  2.197 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      2.126 s ±  0.038 s    [User: 39.090 s, System: 3.107 s]
  Range (min … max):    2.070 s …  2.192 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      5.511 s ±  0.037 s    [User: 27.706 s, System: 3.960 s]
  Range (min … max):    5.436 s …  5.575 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.05 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    2.66 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.568 s ±  0.005 s    [User: 16.927 s, System: 2.896 s]
  Range (min … max):    1.562 s …  1.579 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.586 s ±  0.022 s    [User: 29.435 s, System: 3.584 s]
  Range (min … max):    1.561 s …  1.624 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.545 s ±  0.031 s    [User: 28.214 s, System: 3.117 s]
  Range (min … max):    1.494 s …  1.590 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      5.367 s ±  0.070 s    [User: 21.206 s, System: 3.932 s]
  Range (min … max):    5.283 s …  5.519 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.03 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    3.47 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      2.073 s ±  0.007 s    [User: 23.287 s, System: 2.849 s]
  Range (min … max):    2.066 s …  2.089 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      2.185 s ±  0.021 s    [User: 40.133 s, System: 3.514 s]
  Range (min … max):    2.139 s …  2.203 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      2.130 s ±  0.022 s    [User: 39.043 s, System: 3.088 s]
  Range (min … max):    2.096 s …  2.166 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      5.522 s ±  0.028 s    [User: 27.621 s, System: 3.988 s]
  Range (min … max):    5.472 s …  5.563 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.05 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    2.66 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.553 s ±  0.005 s    [User: 16.732 s, System: 2.890 s]
  Range (min … max):    1.547 s …  1.565 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.585 s ±  0.030 s    [User: 29.014 s, System: 3.555 s]
  Range (min … max):    1.545 s …  1.619 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.541 s ±  0.026 s    [User: 27.788 s, System: 3.131 s]
  Range (min … max):    1.492 s …  1.597 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      5.343 s ±  0.043 s    [User: 20.990 s, System: 3.899 s]
  Range (min … max):    5.249 s …  5.404 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.03 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    3.47 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.466 s ±  0.004 s    [User: 15.581 s, System: 2.881 s]
  Range (min … max):    1.461 s …  1.472 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.175 s ±  0.010 s    [User: 18.765 s, System: 3.690 s]
  Range (min … max):    1.163 s …  1.196 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.133 s ±  0.008 s    [User: 17.881 s, System: 3.220 s]
  Range (min … max):    1.124 s …  1.150 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      5.300 s ±  0.077 s    [User: 20.071 s, System: 3.840 s]
  Range (min … max):    5.221 s …  5.441 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.04 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.29 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    4.68 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):     494.1 ms ±   2.5 ms    [User: 3322.1 ms, System: 2879.8 ms]
  Range (min … max):   490.4 ms … 497.4 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):     393.1 ms ±   2.5 ms    [User: 4283.2 ms, System: 3671.8 ms]
  Range (min … max):   390.1 ms … 397.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):     346.4 ms ±   6.6 ms    [User: 3076.3 ms, System: 3142.9 ms]
  Range (min … max):   336.7 ms … 357.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      4.897 s ±  0.026 s    [User: 7.718 s, System: 3.625 s]
  Range (min … max):    4.862 s …  4.933 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.13 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.43 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5
   14.13 ± 0.28 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.481 s ±  0.004 s    [User: 15.850 s, System: 2.818 s]
  Range (min … max):    1.475 s …  1.488 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.198 s ±  0.011 s    [User: 19.046 s, System: 3.530 s]
  Range (min … max):    1.183 s …  1.220 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.146 s ±  0.014 s    [User: 18.037 s, System: 3.074 s]
  Range (min … max):    1.125 s …  1.162 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      5.291 s ±  0.075 s    [User: 20.231 s, System: 3.764 s]
  Range (min … max):    5.201 s …  5.468 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.05 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.29 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    4.62 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):     438.9 ms ±   1.7 ms    [User: 2494.4 ms, System: 2943.8 ms]
  Range (min … max):   436.0 ms … 442.7 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):     377.2 ms ±   2.8 ms    [User: 2908.1 ms, System: 3428.2 ms]
  Range (min … max):   374.4 ms … 384.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):     332.3 ms ±   2.2 ms    [User: 1730.4 ms, System: 2744.0 ms]
  Range (min … max):   328.8 ms … 334.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      4.889 s ±  0.044 s    [User: 6.948 s, System: 3.658 s]
  Range (min … max):    4.851 s …  5.009 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.14 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.32 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
   14.71 ± 0.16 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.406 s ±  0.006 s    [User: 14.953 s, System: 2.822 s]
  Range (min … max):    1.394 s …  1.414 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.338 s ±  0.012 s    [User: 24.485 s, System: 3.534 s]
  Range (min … max):    1.329 s …  1.371 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      1.302 s ±  0.014 s    [User: 23.364 s, System: 3.091 s]
  Range (min … max):    1.283 s …  1.333 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      5.253 s ±  0.059 s    [User: 19.034 s, System: 3.817 s]
  Range (min … max):    5.210 s …  5.411 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.08 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    4.03 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      3.517 s ±  0.007 s    [User: 41.440 s, System: 2.853 s]
  Range (min … max):    3.508 s …  3.527 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      3.980 s ±  0.031 s    [User: 76.752 s, System: 3.604 s]
  Range (min … max):    3.939 s …  4.018 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      3.961 s ±  0.079 s    [User: 75.187 s, System: 3.164 s]
  Range (min … max):    3.847 s …  4.083 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5
  Time (mean ± σ):      5.933 s ±  0.058 s    [User: 46.163 s, System: 4.067 s]
  Range (min … max):    5.827 s …  6.026 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 ran
    1.13 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.13 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5
    1.69 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5

-------------------------------- 586011 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      2.699 s ±  0.090 s    [User: 24.001 s, System: 5.310 s]
  Range (min … max):    2.508 s …  2.773 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      3.118 s ±  0.039 s    [User: 39.919 s, System: 7.610 s]
  Range (min … max):    3.085 s …  3.208 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      2.990 s ±  0.052 s    [User: 35.403 s, System: 6.540 s]
  Range (min … max):    2.919 s …  3.088 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     12.435 s ±  0.184 s    [User: 35.528 s, System: 8.529 s]
  Range (min … max):   12.265 s … 12.859 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.11 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.16 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    4.61 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      5.196 s ±  0.406 s    [User: 47.511 s, System: 5.288 s]
  Range (min … max):    4.659 s …  5.610 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      6.248 s ±  0.063 s    [User: 81.115 s, System: 7.322 s]
  Range (min … max):    6.154 s …  6.354 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      5.973 s ±  0.073 s    [User: 72.543 s, System: 6.372 s]
  Range (min … max):    5.878 s …  6.104 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     13.392 s ±  0.947 s    [User: 62.969 s, System: 8.853 s]
  Range (min … max):   12.477 s … 15.043 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.15 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.20 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    2.58 ± 0.27 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      3.913 s ±  0.280 s    [User: 34.866 s, System: 5.315 s]
  Range (min … max):    3.536 s …  4.529 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      4.422 s ±  0.040 s    [User: 59.790 s, System: 7.470 s]
  Range (min … max):    4.389 s …  4.523 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      4.234 s ±  0.034 s    [User: 53.888 s, System: 6.414 s]
  Range (min … max):    4.185 s …  4.310 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     13.013 s ±  0.652 s    [User: 47.134 s, System: 8.798 s]
  Range (min … max):   12.481 s … 14.696 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.08 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.13 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    3.33 ± 0.29 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      5.333 s ±  0.380 s    [User: 47.527 s, System: 5.358 s]
  Range (min … max):    4.618 s …  5.630 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      6.159 s ±  0.026 s    [User: 80.495 s, System: 7.328 s]
  Range (min … max):    6.128 s …  6.206 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      5.939 s ±  0.040 s    [User: 71.895 s, System: 6.337 s]
  Range (min … max):    5.881 s …  6.009 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     12.799 s ±  0.174 s    [User: 60.132 s, System: 8.728 s]
  Range (min … max):   12.628 s … 13.204 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.11 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.16 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    2.40 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      3.697 s ±  0.286 s    [User: 33.949 s, System: 5.294 s]
  Range (min … max):    3.295 s …  4.038 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      4.389 s ±  0.033 s    [User: 58.750 s, System: 7.457 s]
  Range (min … max):    4.351 s …  4.441 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      4.188 s ±  0.026 s    [User: 52.459 s, System: 6.497 s]
  Range (min … max):    4.152 s …  4.243 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     12.546 s ±  0.141 s    [User: 45.893 s, System: 8.689 s]
  Range (min … max):   12.415 s … 12.783 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.13 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.19 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    3.39 ± 0.27 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      3.404 s ±  0.271 s    [User: 29.176 s, System: 5.369 s]
  Range (min … max):    2.976 s …  3.626 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      3.574 s ±  0.009 s    [User: 39.573 s, System: 7.706 s]
  Range (min … max):    3.558 s …  3.587 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      3.527 s ±  0.031 s    [User: 36.641 s, System: 6.714 s]
  Range (min … max):    3.499 s …  3.608 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     12.666 s ±  0.193 s    [User: 44.065 s, System: 8.606 s]
  Range (min … max):   12.393 s … 12.958 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.04 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.05 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    3.72 ± 0.30 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     950.9 ms ±   7.9 ms    [User: 6386.6 ms, System: 5290.8 ms]
  Range (min … max):   934.9 ms … 960.7 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     867.3 ms ±   8.8 ms    [User: 9062.5 ms, System: 7375.1 ms]
  Range (min … max):   857.6 ms … 887.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     821.6 ms ±  22.2 ms    [User: 6569.7 ms, System: 6343.1 ms]
  Range (min … max):   800.4 ms … 855.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     11.499 s ±  0.120 s    [User: 17.369 s, System: 7.830 s]
  Range (min … max):   11.385 s … 11.803 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.16 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6
   14.00 ± 0.40 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6
 
    Time (mean ± σ):      3.464 s ±  0.316 s    [User: 29.266 s, System: 5.257 s]
  Range (min … max):    2.965 s …  3.701 s    10 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      3.717 s ±  0.044 s    [User: 40.309 s, System: 7.391 s]
  Range (min … max):    3.667 s …  3.816 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      3.622 s ±  0.033 s    [User: 37.082 s, System: 6.415 s]
  Range (min … max):    3.585 s …  3.691 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     12.683 s ±  0.217 s    [User: 44.542 s, System: 8.462 s]
  Range (min … max):   12.486 s … 13.135 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.05 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.07 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    3.66 ± 0.34 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     831.7 ms ±   7.7 ms    [User: 4725.2 ms, System: 5301.4 ms]
  Range (min … max):   818.8 ms … 841.4 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     798.0 ms ±  15.6 ms    [User: 6311.2 ms, System: 7127.1 ms]
  Range (min … max):   785.1 ms … 835.1 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     738.6 ms ±  11.0 ms    [User: 3837.4 ms, System: 5757.4 ms]
  Range (min … max):   724.0 ms … 754.9 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     11.502 s ±  0.183 s    [User: 15.673 s, System: 7.961 s]
  Range (min … max):   11.329 s … 11.977 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.08 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.13 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
   15.57 ± 0.34 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      3.332 s ±  0.149 s    [User: 30.240 s, System: 5.179 s]
  Range (min … max):    2.922 s …  3.426 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      3.770 s ±  0.026 s    [User: 50.300 s, System: 7.358 s]
  Range (min … max):    3.748 s …  3.829 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):      3.646 s ±  0.044 s    [User: 45.401 s, System: 6.546 s]
  Range (min … max):    3.607 s …  3.727 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     12.564 s ±  0.165 s    [User: 42.072 s, System: 8.493 s]
  Range (min … max):   12.361 s … 12.916 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.09 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.13 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    3.77 ± 0.18 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      9.696 s ±  0.546 s    [User: 85.152 s, System: 5.414 s]
  Range (min … max):    8.195 s … 10.041 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     11.296 s ±  0.173 s    [User: 150.403 s, System: 7.515 s]
  Range (min … max):   11.142 s … 11.693 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     10.914 s ±  0.221 s    [User: 135.115 s, System: 6.524 s]
  Range (min … max):   10.673 s … 11.309 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6
  Time (mean ± σ):     14.661 s ±  0.203 s    [User: 100.171 s, System: 9.155 s]
  Range (min … max):   14.431 s … 15.088 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 ran
    1.13 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.17 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6
    1.51 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6

-----------------------------------------------------
-------------------- "min" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0720140658    0.0715389378    0.0778230328    0.1958784288    0.1166856789    0.1159839999    0.1447034119    0.2617366629    0.0899894196    0.0892570976    0.1065350776    0.2225640416    0.1168279362    0.1154997772    0.1444257632    0.2611045842    0.0896836773    0.0891248233    0.1059616983    0.2236779933        0.0879015894    0.0871791704    0.1010733604    0.2190554254    0.0373096225    0.0363836475    0.0280964505    0.1735544315    0.0885830029    0.0877224479    0.1020863319    0.2208352539    0.0347112350    0.0347021100    0.0238083390    0.1727048460    0.0824039877    0.0812677757    0.09458927470.2130415827    0.1882995872    0.1861255972    0.2503667862    0.3634730732
4096    0.0638682738    0.0592073238    0.0580293348    0.2207927728    0.0950859360    0.0890137720    0.0965258610    0.2288399540    0.0773233623    0.0712922223    0.0766395153    0.2187606083    0.0931186343    0.0888209203    0.0961686883    0.2283700403    0.0765259911    0.0708898161    0.0752591011    0.2215628791        0.0739980324    0.0697352564    0.0711563784    0.2192987874    0.0426244240    0.0404836140    0.0297048520    0.2221337060    0.0745144793    0.0705096813    0.0711839373    0.2193682903    0.0405472823    0.0386013433    0.0261853663    0.2222943503    0.0732737545    0.0662936505    0.06938747950.2204568105    0.1408769846    0.1292949796    0.1565950956    0.2671448136
16384   0.1853851151    0.1804340121    0.2377136931    0.4693761391    0.3301720710    0.3328967430    0.4664603460    0.5493069430    0.2451010167    0.2419081227    0.3315940487    0.4993423177    0.3305792774    0.3319255804    0.4662994454    0.5492947714    0.2436123202    0.2421475972    0.3292133472    0.4975778762        0.2350069789    0.2327270899    0.3178858839    0.4947367529    0.0778135698    0.0717712628    0.0676779878    0.4462141698    0.2378581887    0.2366154197    0.3230015177    0.4945179577    0.0685784581    0.0637282951    0.0541754931    0.4450342721    0.2200508787    0.2168657857    0.29028982270.4837518177    0.5707794743    0.5703577323    0.8319387163    0.7689591103
65536   0.3139967048    0.2810834038    0.2798628968    1.3464359548    0.5487299202    0.5165963071    0.5441121762    1.4087664412    0.4175656404    0.3765205624    0.4097774454    1.3586250364    0.5459616963    0.4885190323    0.5244720953    1.4118135643    0.4103298242    0.3845099182    0.4080822122    1.3659440852        0.3920137789    0.3146790459    0.3095130269    1.3559874679    0.143170976,    0.122127176,    0.1048578,      1.324580939,    0.3973616680    0.3105865270    0.3170609200    1.3535159450    0.1280241007    0.1142146807    0.0961447197    1.3218218737    0.3759888736    0.3308200876    0.32732998261.3464432506    0.9138809043    0.8591794683    0.9277263903    1.5488937543
262144  1.1651401767    1.0999093947    1.0379437098    5.1346067148    2.0668740309    2.1537567079    2.0700565479    5.4360304219    1.5624166344    1.5613348194    1.4943696584    5.2825603874    2.0655824605    2.1392491125    2.0957033055    5.4723320675    1.5467099573    1.5446389523    1.4922184523    5.2493848543        1.4606179360    1.1631520540    1.1241861380    5.2212703890    0.4903626803    0.3900770143    0.3367049603    4.8621949663    1.4751637515    1.1830379645    1.1254813065    5.2005725705    0.4359625063    0.3743609583    0.3287579493    4.8509287473    1.3944573423    1.3292652943    1.28264162135.2100171933    3.5083746968    3.9394703858    3.8474507518    5.8272985618
586011  2.5076215111    3.0848553820    2.9191441171    12.265090636    4.6590724813    6.1537401253    5.8784012783    12.476588978    3.5355289603    4.3885600424    4.1854607624    12.480938284    4.6176061286    6.1277715396    5.8806226706    12.628304850    3.2951100004    4.3506937694    4.1517717874    12.414616312        2.9757512442    3.5584933062    3.4986471462    12.393310289    0.9348566881    0.8576087961    0.8004258451    11.385486920    2.9654837625    3.6669596655    3.5845206935    12.486115322    0.8188030884    0.7851434654    0.7240438544    11.329255636    2.9222558091    3.7483908221    3.607454390112.360566964    8.1951351581    11.142394748    10.672698764    14.431046857

-----------------------------------------------------
-------------------- "mean" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0725585474    0.0720929557    0.0788001077    0.1979509852    0.1176360906    0.1167646198    0.1457442108    0.2639306147    0.0911017573    0.0900386156    0.1073541361    0.2251327879    0.1175866648    0.1166149133    0.1455646789    0.2624057001    0.0909394508    0.0900077079    0.1064774848    0.2247994134        0.0885755041    0.0881463407    0.1019697132    0.2205417194    0.0377489504    0.0369515333    0.0289429940    0.1746979773    0.0899070054    0.0885255944    0.1030114130    0.2227593301    0.0351437667    0.0352322614    0.0246590697    0.1744455326    0.0831865434    0.0820973445    0.09522352000.2136706209    0.1889330552    0.1875064983    0.2515206285    0.3644831379
4096    0.0657043025    0.0622539853    0.0587040249    0.2225878846    0.0963533337    0.0901931893    0.0973709885    0.2296014789    0.0796251343    0.0752700382    0.0772503854    0.2230447776    0.0953938574    0.0906050505    0.0971342035    0.2292712747    0.0792331150    0.0743581341    0.0760410250    0.2242969969        0.0764554407    0.0721325985    0.0719504217    0.2225285992    0.0437055571    0.0415440609    0.0303103379    0.2243049652    0.0765108093    0.0729445631    0.0718773724    0.2227912818    0.0412267145    0.0393255141    0.0268335436    0.2247335066    0.0747154217    0.0707681028    0.07015793990.2224140355    0.1430648979    0.1335950296    0.1570131829    0.2683157350
16384   0.1867015253    0.1969434563    0.2386977186    0.4715072541    0.3322351298    0.3583199901    0.4681176950    0.5537797738    0.2467307059    0.2561876953    0.3326483924    0.5018347472    0.3325379478    0.3581663335    0.4685610028    0.5520236175    0.2457841650    0.2606458978    0.3298648045    0.5025861434        0.2357228265    0.2354668025    0.3183990356    0.4981314302    0.0807566526    0.0752002162    0.0683035072    0.4497789642    0.2385188904    0.2423304082    0.3236779935    0.4994696362    0.0722047824    0.0668172833    0.0547409313    0.4487276400    0.2219382671    0.2431867819    0.29184873500.4871172812    0.5732426427    0.5976080648    0.8362951948    0.7714800347
65536   0.3166234583    0.3081969813    0.2892968194    1.3709664832    0.5588102563    0.5361554151    0.5634634153    1.4267971958    0.4208754423    0.4118677542    0.4241373676    1.3731973373    0.5501920427    0.5234951369    0.5569853392    1.4289820404    0.4157531883    0.3982773591    0.4202099000    1.3734294131        0.3948152193    0.3225332777    0.3230644961    1.3656759629    0.1450227967    0.1265254470    0.1112041135    1.3396630351    0.3994018897    0.3210762502    0.3285114489    1.3695607271    0.1309943854    0.1192536441    0.0987002132    1.3302864768    0.379415918,    0.3492759867    0.37177218531.3641621178    0.9215685345    0.9128113504    0.9739906008    1.5556143428
262144  1.1691990819    1.1143811324    1.0678331323    5.1917066165    2.0756542913    2.1749040468    2.1260143537    5.5108992503    1.5682774363    1.5860477947    1.5453862143    5.3672893988    2.0726675314    2.1845690247    2.1302818910    5.5215304415    1.5533092229    1.5852053605    1.5408653424    5.3432020748        1.4656343381    1.1748666538    1.1325501433    5.2998418160    0.4941002657    0.3930854348    0.3464444167    4.8966754667    1.4812141555    1.1980802051    1.1455858101    5.2912711698    0.4389497101    0.3772458474    0.3323412783    4.8892325534    1.4064487610    1.3383431377    1.30224339075.2526404905    3.5168986116    3.9799941909    3.9605970642    5.9331419742
586011  2.6989329360    3.1175157159    2.9904085499    12.434668815    5.1956187172    6.2479048200    5.9725777802    13.392190694    3.9128132755    4.4216966319    4.2344596606    13.013352871    5.3326558179    6.1593330569    5.9391213842    12.798612435    3.6970332571    4.3892427704    4.1878367560    12.546256798        3.4040184367    3.5744967019    3.5274427026    12.665717266    0.9508656814    0.8673272787    0.8216162715    11.499220428    3.4640789743    3.7169466691    3.6217599301    12.683057313    0.8317092173    0.7979606116    0.7386253343    11.501837499    3.3318977637    3.7699765853    3.646029245012.563921917    9.6956941663    11.295862557    10.914177753    14.661217500

-----------------------------------------------------
-------------------- "max" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0738166368    0.0734427308    0.0798069538    0.2004875718    0.1217400089    0.1182711409    0.1507883839    0.2732017649    0.0940226396    0.0907782286    0.1091680586    0.2317299946    0.1187080482    0.1193520742    0.1480161022    0.2666278352    0.0949815873    0.0914511683    0.1072929893    0.2256736543        0.0898847094    0.0900213564    0.1039532684    0.2219309434    0.0390645265    0.0383061045    0.0302883875    0.1758868965    0.0911009269    0.0899827029    0.1038298979    0.2262308439    0.0362522110    0.0363041230    0.0270519190    0.1777873830    0.0846861607    0.0833018647    0.09701513270.2170188737    0.1905441292    0.1932296032    0.2534854102    0.3648246852
4096    0.0676470518    0.0654126438    0.0603797448    0.2241473188    0.1001542100    0.0951440300    0.0981010890    0.2322968530    0.0820887803    0.0786742043    0.0780991143    0.2305880863    0.0983283733    0.0951098603    0.0994546213    0.2301267943    0.0819666681    0.0768773891    0.0775607531    0.2283316791        0.0809978824    0.0755701044    0.0755376974    0.2257517184    0.0449630010    0.0434433700    0.0314184270    0.2306003840    0.0790996443    0.0761248333    0.0728828003    0.2256472263    0.0424536723    0.0413563903    0.0284454393    0.2271382023    0.0756911525    0.0746660495    0.07267488350.2240809415    0.1535530836    0.1372545856    0.1584771606    0.2690296916
16384   0.1895029561    0.2346703081    0.2404085861    0.4751805271    0.3365306530    0.3953014440    0.4721789540    0.5640421740    0.2512316987    0.2790464697    0.3370805157    0.5042062267    0.3360562624    0.3975649714    0.4842112524    0.5548462964    0.2509354012    0.2876564162    0.3305545102    0.5096590262        0.2371971909    0.2420551309    0.3187289719    0.5087400359    0.0916835108    0.0878753408    0.0690058718    0.4556144058    0.2394509847    0.2490364007    0.3250401497    0.5020893567    0.0798742491    0.0760027421    0.0558580521    0.4531628541    0.2257184087    0.2769954967    0.29233767270.4908155137    0.5803875313    0.6478112833    0.8627664963    0.7785580493
65536   0.3190960238    0.3238684318    0.2987726168    1.4077201968    0.5908997582    0.5635989612    0.5814586622    1.4412808432    0.4231944564    0.4403311214    0.4367603874    1.3838084734    0.5555231103    0.5557203083    0.5767048783    1.4572677913    0.4202721472    0.4257392042    0.4463712902    1.3877677602        0.3969496419    0.3335549019    0.3383024169    1.3794064639    0.1469119910    0.131544528,    0.124578314,    1.358658343,    0.4015937540    0.3389660640    0.3391388450    1.4124723670    0.1343263347    0.1242120947    0.1114135697    1.3529381987    0.3842677726    0.3725145536    0.39485969861.4120243066    0.9275188303    0.9663556173    1.0030019973    1.5716534443
262144  1.1814253477    1.1463997447    1.1014127647    5.3305028688    2.0849707379    2.1970370169    2.1918007799    5.5746418219    1.5787292294    1.6237667274    1.5897691734    5.5185625414    2.0889248875    2.2025495165    2.1662191015    5.5633970035    1.5645673683    1.6191437803    1.5969583783    5.4040723233        1.4719534160    1.1961592600    1.1495461230    5.4407605820    0.4973891783    0.3977167983    0.3575872973    4.9334052973    1.4876905925    1.2201275525    1.1616021475    5.4684210905    0.4427345103    0.3844286353    0.3345872603    5.0088046853    1.4144427183    1.3705423503    1.33266560535.4109910343    3.5273125708    4.0183035468    4.0827547348    6.0264040818
586011  2.7734343300    3.2081877900    3.0878785760    12.859205217    5.6100467253    6.3535995303    6.1035899963    15.043334142    4.5293638964    4.5225539014    4.3103039784    14.695705439    5.6297346956    6.2059169496    6.0090135806    13.203812435    4.0376893994    4.4406897594    4.2434941274    12.782996579        3.6260889442    3.5868661292    3.6079079272    12.957799825    0.9607434791    0.8879400111    0.8549984711    11.802916580    3.7008920175    3.8158377825    3.6909479345    13.134993589    0.8413749844    0.8350856024    0.7549209374    11.976963507    3.4264187281    3.8287371231    3.727393540112.915575639    10.041360793    11.692549018    11.308724844    15.087994443


||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0725585474    0.0720929557    0.0788001077    0.1979509852    forkrun is 9.303% faster than xargs (1.0930x)   forkrun is 174.5% faster than parallel (2.7457x)
sha256sum       0.1176360906    0.1167646198    0.1457442108    0.2639306147    forkrun is 24.81% faster than xargs (1.2481x)   forkrun is 126.0% faster than parallel (2.2603x)
sha512sum       0.0911017573    0.0900386156    0.1073541361    0.2251327879    forkrun is 19.23% faster than xargs (1.1923x)   forkrun is 150.0% faster than parallel (2.5004x)
sha224sum       0.1175866648    0.1166149133    0.1455646789    0.2624057001    forkrun is 24.82% faster than xargs (1.2482x)   forkrun is 125.0% faster than parallel (2.2501x)
sha384sum       0.0909394508    0.0900077079    0.1064774848    0.2247994134    forkrun is 18.29% faster than xargs (1.1829x)   forkrun is 149.7% faster than parallel (2.4975x)
md5sum          0.0885755041    0.0881463407    0.1019697132    0.2205417194    forkrun is 15.68% faster than xargs (1.1568x)   forkrun is 150.1% faster than parallel (2.5019x)
sum -s          0.0377489504    0.0369515333    0.0289429940    0.1746979773    xargs is 27.67% faster than forkrun (1.2767x)   forkrun is 372.7% faster than parallel (4.7277x)
sum -r          0.0899070054    0.0885255944    0.1030114130    0.2227593301    forkrun is 16.36% faster than xargs (1.1636x)   forkrun is 151.6% faster than parallel (2.5163x)
cksum           0.0351437667    0.0352322614    0.0246590697    0.1744455326    xargs is 42.51% faster than forkrun (1.4251x)   forkrun is 396.3% faster than parallel (4.9637x)
b2sum           0.0831865434    0.0820973445    0.0952235200    0.2136706209    forkrun is 15.98% faster than xargs (1.1598x)   forkrun is 160.2% faster than parallel (2.6026x)
cksum -a sm3    0.1889330552    0.1875064983    0.2515206285    0.3644831379    forkrun is 33.12% faster than xargs (1.3312x)   forkrun is 92.91% faster than parallel (1.9291x)

OVERALL         1.0133173366    1.0039783854    1.1892679571    2.5448178201    forkrun is 18.45% faster than xargs (1.1845x)   forkrun is 153.4% faster than parallel (2.5347x)




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0657043025    0.0622539853    0.0587040249    0.2225878846    xargs is 11.92% faster than forkrun (1.1192x)   forkrun is 238.7% faster than parallel (3.3877x)
sha256sum       0.0963533337    0.0901931893    0.0973709885    0.2296014789    forkrun is 1.056% faster than xargs (1.0105x)   forkrun is 138.2% faster than parallel (2.3829x)
sha512sum       0.0796251343    0.0752700382    0.0772503854    0.2230447776    xargs is 3.074% faster than forkrun (1.0307x)   forkrun is 180.1% faster than parallel (2.8011x)
sha224sum       0.0953938574    0.0906050505    0.0971342035    0.2292712747    forkrun is 7.206% faster than xargs (1.0720x)   forkrun is 153.0% faster than parallel (2.5304x)
sha384sum       0.0792331150    0.0743581341    0.0760410250    0.2242969969    xargs is 4.197% faster than forkrun (1.0419x)   forkrun is 183.0% faster than parallel (2.8308x)
md5sum          0.0764554407    0.0721325985    0.0719504217    0.2225285992    xargs is 6.261% faster than forkrun (1.0626x)   forkrun is 191.0% faster than parallel (2.9105x)
sum -s          0.0437055571    0.0415440609    0.0303103379    0.2243049652    xargs is 37.06% faster than forkrun (1.3706x)   forkrun is 439.9% faster than parallel (5.3992x)
sum -r          0.0765108093    0.0729445631    0.0718773724    0.2227912818    xargs is 1.484% faster than forkrun (1.0148x)   forkrun is 205.4% faster than parallel (3.0542x)
cksum           0.0412267145    0.0393255141    0.0268335436    0.2247335066    xargs is 46.55% faster than forkrun (1.4655x)   forkrun is 471.4% faster than parallel (5.7146x)
b2sum           0.0747154217    0.0707681028    0.0701579399    0.2224140355    xargs is .8696% faster than forkrun (1.0086x)   forkrun is 214.2% faster than parallel (3.1428x)
cksum -a sm3    0.1430648979    0.1335950296    0.1570131829    0.2683157350    forkrun is 17.52% faster than xargs (1.1752x)   forkrun is 100.8% faster than parallel (2.0084x)

OVERALL         .87198858460    .82299026678    .83464342627    2.5138905363    xargs is 4.474% faster than forkrun (1.0447x)   forkrun is 188.2% faster than parallel (2.8829x)




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.1867015253    0.1969434563    0.2386977186    0.4715072541    forkrun is 27.84% faster than xargs (1.2784x)   forkrun is 152.5% faster than parallel (2.5254x)
sha256sum       0.3322351298    0.3583199901    0.4681176950    0.5537797738    forkrun is 40.89% faster than xargs (1.4089x)   forkrun is 66.68% faster than parallel (1.6668x)
sha512sum       0.2467307059    0.2561876953    0.3326483924    0.5018347472    forkrun is 29.84% faster than xargs (1.2984x)   forkrun is 95.88% faster than parallel (1.9588x)
sha224sum       0.3325379478    0.3581663335    0.4685610028    0.5520236175    forkrun is 40.90% faster than xargs (1.4090x)   forkrun is 66.00% faster than parallel (1.6600x)
sha384sum       0.2457841650    0.2606458978    0.3298648045    0.5025861434    forkrun is 26.55% faster than xargs (1.2655x)   forkrun is 92.82% faster than parallel (1.9282x)
md5sum          0.2357228265    0.2354668025    0.3183990356    0.4981314302    forkrun is 35.22% faster than xargs (1.3522x)   forkrun is 111.5% faster than parallel (2.1155x)
sum -s          0.0807566526    0.0752002162    0.0683035072    0.4497789642    xargs is 18.23% faster than forkrun (1.1823x)   forkrun is 456.9% faster than parallel (5.5695x)
sum -r          0.2385188904    0.2423304082    0.3236779935    0.4994696362    forkrun is 35.70% faster than xargs (1.3570x)   forkrun is 109.4% faster than parallel (2.0940x)
cksum           0.0722047824    0.0668172833    0.0547409313    0.4487276400    xargs is 22.06% faster than forkrun (1.2206x)   forkrun is 571.5% faster than parallel (6.7157x)
b2sum           0.2219382671    0.2431867819    0.2918487350    0.4871172812    forkrun is 31.49% faster than xargs (1.3149x)   forkrun is 119.4% faster than parallel (2.1948x)
cksum -a sm3    0.5732426427    0.5976080648    0.8362951948    0.7714800347    forkrun is 45.88% faster than xargs (1.4588x)   forkrun is 34.58% faster than parallel (1.3458x)

OVERALL         2.7663735360    2.8908729306    3.7311550111    5.7364365229    forkrun is 34.87% faster than xargs (1.3487x)   forkrun is 107.3% faster than parallel (2.0736x)




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.3166234583    0.3081969813    0.2892968194    1.3709664832    xargs is 6.533% faster than forkrun (1.0653x)   forkrun is 344.8% faster than parallel (4.4483x)
sha256sum       0.5588102563    0.5361554151    0.5634634153    1.4267971958    forkrun is 5.093% faster than xargs (1.0509x)   forkrun is 166.1% faster than parallel (2.6611x)
sha512sum       0.4208754423    0.4118677542    0.4241373676    1.3731973373    forkrun is .7750% faster than xargs (1.0077x)   forkrun is 226.2% faster than parallel (3.2627x)
sha224sum       0.5501920427    0.5234951369    0.5569853392    1.4289820404    forkrun is 6.397% faster than xargs (1.0639x)   forkrun is 172.9% faster than parallel (2.7296x)
sha384sum       0.4157531883    0.3982773591    0.4202099000    1.3734294131    forkrun is 5.506% faster than xargs (1.0550x)   forkrun is 244.8% faster than parallel (3.4484x)
md5sum          0.3948152193    0.3225332777    0.3230644961    1.3656759629    forkrun is .1647% faster than xargs (1.0016x)   forkrun is 323.4% faster than parallel (4.2342x)
sum -s          0.1450227967    0.1265254470    0.1112041135    1.3396630351    xargs is 30.41% faster than forkrun (1.3041x)   forkrun is 823.7% faster than parallel (9.2376x)
sum -r          0.3994018897    0.3210762502    0.3285114489    1.3695607271    xargs is 21.57% faster than forkrun (1.2157x)   forkrun is 242.9% faster than parallel (3.4290x)
cksum           0.1309943854    0.1192536441    0.0987002132    1.3302864768    xargs is 32.71% faster than forkrun (1.3271x)   forkrun is 915.5% faster than parallel (10.155x)
b2sum           0.379415918     0.3492759867    0.3717721853    1.3641621178    xargs is 2.056% faster than forkrun (1.0205x)   forkrun is 259.5% faster than parallel (3.5954x)
cksum -a sm3    0.9215685345    0.9128113504    0.9739906008    1.5556143428    forkrun is 6.702% faster than xargs (1.0670x)   forkrun is 70.42% faster than parallel (1.7042x)

OVERALL         4.6334731319    4.3294686032    4.4613358997    15.298335132    forkrun is 3.045% faster than xargs (1.0304x)   forkrun is 253.3% faster than parallel (3.5335x)




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         1.1691990819    1.1143811324    1.0678331323    5.1917066165    xargs is 4.359% faster than forkrun (1.0435x)   forkrun is 365.8% faster than parallel (4.6588x)
sha256sum       2.0756542913    2.1749040468    2.1260143537    5.5108992503    xargs is 2.299% faster than forkrun (1.0229x)   forkrun is 153.3% faster than parallel (2.5338x)
sha512sum       1.5682774363    1.5860477947    1.5453862143    5.3672893988    xargs is 2.631% faster than forkrun (1.0263x)   forkrun is 238.4% faster than parallel (3.3840x)
sha224sum       2.0726675314    2.1845690247    2.1302818910    5.5215304415    xargs is 2.548% faster than forkrun (1.0254x)   forkrun is 152.7% faster than parallel (2.5275x)
sha384sum       1.5533092229    1.5852053605    1.5408653424    5.3432020748    xargs is .8075% faster than forkrun (1.0080x)   forkrun is 243.9% faster than parallel (3.4398x)
md5sum          1.4656343381    1.1748666538    1.1325501433    5.2998418160    xargs is 3.736% faster than forkrun (1.0373x)   forkrun is 351.1% faster than parallel (4.5110x)
sum -s          0.4941002657    0.3930854348    0.3464444167    4.8966754667    xargs is 13.46% faster than forkrun (1.1346x)   forkrun is 1145.% faster than parallel (12.457x)
sum -r          1.4812141555    1.1980802051    1.1455858101    5.2912711698    xargs is 29.29% faster than forkrun (1.2929x)   forkrun is 257.2% faster than parallel (3.5722x)
cksum           0.4389497101    0.3772458474    0.3323412783    4.8892325534    xargs is 32.07% faster than forkrun (1.3207x)   forkrun is 1013.% faster than parallel (11.138x)
b2sum           1.4064487610    1.3383431377    1.3022433907    5.2526404905    xargs is 8.001% faster than forkrun (1.0800x)   forkrun is 273.4% faster than parallel (3.7346x)
cksum -a sm3    3.5168986116    3.9799941909    3.9605970642    5.9331419742    forkrun is 12.61% faster than xargs (1.1261x)   forkrun is 68.70% faster than parallel (1.6870x)

OVERALL         17.242353406    17.106722829    16.630143037    58.497431252    xargs is 2.865% faster than forkrun (1.0286x)   forkrun is 241.9% faster than parallel (3.4195x)




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         2.6989329360    3.1175157159    2.9904085499    12.434668815    forkrun is 10.79% faster than xargs (1.1079x)   forkrun is 360.7% faster than parallel (4.6072x)
sha256sum       5.1956187172    6.2479048200    5.9725777802    13.392190694    forkrun is 14.95% faster than xargs (1.1495x)   forkrun is 157.7% faster than parallel (2.5775x)
sha512sum       3.9128132755    4.4216966319    4.2344596606    13.013352871    forkrun is 8.220% faster than xargs (1.0822x)   forkrun is 232.5% faster than parallel (3.3258x)
sha224sum       5.3326558179    6.1593330569    5.9391213842    12.798612435    forkrun is 11.37% faster than xargs (1.1137x)   forkrun is 140.0% faster than parallel (2.4000x)
sha384sum       3.6970332571    4.3892427704    4.1878367560    12.546256798    forkrun is 13.27% faster than xargs (1.1327x)   forkrun is 239.3% faster than parallel (3.3936x)
md5sum          3.4040184367    3.5744967019    3.5274427026    12.665717266    forkrun is 3.625% faster than xargs (1.0362x)   forkrun is 272.0% faster than parallel (3.7208x)
sum -s          0.9508656814    0.8673272787    0.8216162715    11.499220428    xargs is 5.563% faster than forkrun (1.0556x)   forkrun is 1225.% faster than parallel (13.258x)
sum -r          3.4640789743    3.7169466691    3.6217599301    12.683057313    forkrun is 4.551% faster than xargs (1.0455x)   forkrun is 266.1% faster than parallel (3.6613x)
cksum           0.8317092173    0.7979606116    0.7386253343    11.501837499    xargs is 12.60% faster than forkrun (1.1260x)   forkrun is 1282.% faster than parallel (13.829x)
b2sum           3.3318977637    3.7699765853    3.6460292450    12.563921917    forkrun is 9.428% faster than xargs (1.0942x)   forkrun is 277.0% faster than parallel (3.7708x)
cksum -a sm3    9.6956941663    11.295862557    10.914177753    14.661217500    forkrun is 12.56% faster than xargs (1.1256x)   forkrun is 51.21% faster than parallel (1.5121x)

OVERALL         42.515318244    48.358263399    46.594055368    139.76005354    forkrun is 9.593% faster than xargs (1.0959x)   forkrun is 228.7% faster than parallel (3.2872x)


-------------------------------- 1024 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha1sum 
  Time (mean ± σ):      73.0 ms ±   0.4 ms    [User: 89.7 ms, System: 40.9 ms]
  Range (min … max):    72.5 ms …  74.8 ms    39 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha1sum 
  Time (mean ± σ):      72.7 ms ±   0.5 ms    [User: 92.9 ms, System: 44.4 ms]
  Range (min … max):    72.1 ms …  74.2 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha1sum 
  Time (mean ± σ):      78.8 ms ±   0.6 ms    [User: 65.1 ms, System: 14.3 ms]
  Range (min … max):    78.2 ms …  80.5 ms    36 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha1sum 
  Time (mean ± σ):     198.8 ms ±   1.3 ms    [User: 212.0 ms, System: 147.8 ms]
  Range (min … max):   197.3 ms … 202.2 ms    14 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha1sum  ran
    1.00 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha1sum 
    1.08 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha1sum 
    2.73 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha1sum 

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha256sum 
  Time (mean ± σ):     117.9 ms ±   0.6 ms    [User: 158.1 ms, System: 40.3 ms]
  Range (min … max):   117.3 ms … 119.3 ms    24 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha256sum 
  Time (mean ± σ):     116.9 ms ±   0.7 ms    [User: 158.4 ms, System: 46.6 ms]
  Range (min … max):   115.8 ms … 119.0 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha256sum 
  Time (mean ± σ):     145.3 ms ±   0.9 ms    [User: 131.0 ms, System: 14.8 ms]
  Range (min … max):   144.1 ms … 147.2 ms    19 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha256sum 
  Time (mean ± σ):     262.7 ms ±   0.5 ms    [User: 283.4 ms, System: 144.1 ms]
  Range (min … max):   261.8 ms … 263.6 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha256sum  ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha256sum 
    1.24 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha256sum 
    2.25 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha256sum 

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha512sum 
  Time (mean ± σ):      91.5 ms ±   0.6 ms    [User: 117.8 ms, System: 42.0 ms]
  Range (min … max):    90.6 ms …  93.6 ms    31 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha512sum 
  Time (mean ± σ):      90.7 ms ±   0.4 ms    [User: 121.8 ms, System: 44.5 ms]
  Range (min … max):    90.0 ms …  91.9 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha512sum 
  Time (mean ± σ):     107.0 ms ±   0.7 ms    [User: 93.7 ms, System: 13.8 ms]
  Range (min … max):   106.3 ms … 109.0 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha512sum 
  Time (mean ± σ):     225.1 ms ±   0.5 ms    [User: 240.7 ms, System: 147.3 ms]
  Range (min … max):   224.4 ms … 226.1 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha512sum  ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha512sum 
    1.18 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha512sum 
    2.48 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha512sum 

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha224sum 
 
  Warning  Time (mean ± σ):     117.9 ms ±   0.8 ms    [User: 158.4 ms, System: 39.7 ms]
  Range (min … max):   116.7 ms … 121.0 ms    24 runs
: The first benchmarking run for this command was significantly slower than the rest (121.0 ms). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha224sum 
  Time (mean ± σ):     117.1 ms ±   0.6 ms    [User: 159.8 ms, System: 45.1 ms]
  Range (min … max):   116.4 ms … 118.2 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha224sum 
  Time (mean ± σ):     144.8 ms ±   0.5 ms    [User: 130.3 ms, System: 15.0 ms]
  Range (min … max):   144.1 ms … 145.6 ms    20 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha224sum 
  Time (mean ± σ):     262.3 ms ±   0.6 ms    [User: 282.8 ms, System: 144.5 ms]
  Range (min … max):   261.3 ms … 263.2 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha224sum  ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha224sum 
    1.24 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha224sum 
    2.24 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha224sum 

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha384sum 
  Time (mean ± σ):      91.1 ms ±   0.3 ms    [User: 118.0 ms, System: 40.8 ms]
  Range (min … max):    90.2 ms …  91.9 ms    31 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha384sum 
  Time (mean ± σ):      90.6 ms ±   0.6 ms    [User: 121.3 ms, System: 44.1 ms]
  Range (min … max):    89.7 ms …  92.1 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha384sum 
  Time (mean ± σ):     106.3 ms ±   0.7 ms    [User: 91.2 ms, System: 15.6 ms]
  Range (min … max):   105.6 ms … 108.0 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha384sum 
  Time (mean ± σ):     224.7 ms ±   0.7 ms    [User: 242.4 ms, System: 145.3 ms]
  Range (min … max):   223.6 ms … 226.2 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha384sum  ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha384sum 
    1.17 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha384sum 
    2.48 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha384sum 

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- md5sum 
  Time (mean ± σ):      89.0 ms ±   0.3 ms    [User: 113.5 ms, System: 40.9 ms]
  Range (min … max):    88.4 ms …  89.8 ms    32 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- md5sum 
  Time (mean ± σ):      88.7 ms ±   0.5 ms    [User: 115.8 ms, System: 45.3 ms]
  Range (min … max):    88.0 ms …  90.1 ms    32 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- md5sum 
  Time (mean ± σ):     102.1 ms ±   0.8 ms    [User: 87.7 ms, System: 15.0 ms]
  Range (min … max):   101.3 ms … 105.3 ms    28 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- md5sum 
  Time (mean ± σ):     220.8 ms ±   0.6 ms    [User: 235.1 ms, System: 147.9 ms]
  Range (min … max):   219.3 ms … 221.6 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- md5sum  ran
    1.00 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- md5sum 
    1.15 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- md5sum 
    2.49 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- md5sum 

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -s 
  Time (mean ± σ):      38.3 ms ±   0.2 ms    [User: 40.1 ms, System: 37.7 ms]
  Range (min … max):    38.0 ms …  39.0 ms    72 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -s 
  Time (mean ± σ):      37.5 ms ±   0.2 ms    [User: 40.2 ms, System: 40.5 ms]
  Range (min … max):    37.1 ms …  38.3 ms    73 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -s 
  Time (mean ± σ):      29.0 ms ±   0.3 ms    [User: 14.7 ms, System: 15.1 ms]
  Range (min … max):    28.2 ms …  29.7 ms    93 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -s 
  Time (mean ± σ):     174.5 ms ±   0.9 ms    [User: 158.2 ms, System: 139.8 ms]
  Range (min … max):   173.3 ms … 177.1 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -s  ran
    1.29 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -s 
    1.32 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -s 
    6.01 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -s 

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -r 
  Time (mean ± σ):      90.2 ms ±   0.4 ms    [User: 115.3 ms, System: 38.2 ms]
  Range (min … max):    89.5 ms …  91.1 ms    32 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -r 
  Time (mean ± σ):      89.2 ms ±   0.4 ms    [User: 117.1 ms, System: 42.6 ms]
  Range (min … max):    88.4 ms …  90.0 ms    32 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -r 
  Time (mean ± σ):     102.7 ms ±   0.3 ms    [User: 89.1 ms, System: 14.1 ms]
  Range (min … max):   102.1 ms … 103.3 ms    28 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -r 
  Time (mean ± σ):     222.0 ms ±   0.7 ms    [User: 232.5 ms, System: 141.0 ms]
  Range (min … max):   221.1 ms … 223.8 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -r  ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -r 
    1.15 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -r 
    2.49 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -r 

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum 
  Time (mean ± σ):      35.7 ms ±   0.2 ms    [User: 36.0 ms, System: 39.1 ms]
  Range (min … max):    35.4 ms …  36.3 ms    76 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum 
  Time (mean ± σ):      35.8 ms ±   0.1 ms    [User: 38.7 ms, System: 43.6 ms]
  Range (min … max):    35.4 ms …  36.2 ms    76 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum 
  Time (mean ± σ):      24.6 ms ±   0.3 ms    [User: 11.4 ms, System: 14.1 ms]
  Range (min … max):    24.1 ms …  25.7 ms    104 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum 
  Time (mean ± σ):     175.0 ms ±   0.9 ms    [User: 159.6 ms, System: 145.8 ms]
  Range (min … max):   173.2 ms … 176.9 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum  ran
    1.45 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum 
    1.45 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum 
    7.10 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum 

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- b2sum 
  Time (mean ± σ):      83.8 ms ±   0.5 ms    [User: 107.3 ms, System: 38.2 ms]
  Range (min … max):    83.0 ms …  85.1 ms    34 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- b2sum 
  Time (mean ± σ):      82.7 ms ±   0.5 ms    [User: 109.4 ms, System: 41.6 ms]
  Range (min … max):    81.8 ms …  85.0 ms    34 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- b2sum 
  Time (mean ± σ):      95.1 ms ±   0.4 ms    [User: 80.7 ms, System: 15.0 ms]
  Range (min … max):    94.4 ms …  96.2 ms    30 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- b2sum 
  Time (mean ± σ):     213.7 ms ±   0.6 ms    [User: 224.1 ms, System: 141.2 ms]
  Range (min … max):   212.7 ms … 214.6 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- b2sum  ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- b2sum 
    1.15 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- b2sum 
    2.58 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- b2sum 

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum -a sm3 
 
  Warning  Time (mean ± σ):     189.3 ms ±   1.6 ms    [User: 264.3 ms, System: 41.2 ms]
  Range (min … max):   188.4 ms … 195.0 ms    15 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum -a sm3 
  Time (mean ± σ):     187.2 ms ±   0.6 ms    [User: 266.8 ms, System: 47.6 ms]
  Range (min … max):   186.4 ms … 187.9 ms    15 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
 
  Warning  Time (mean ± σ):     250.7 ms ±   1.7 ms    [User: 236.4 ms, System: 14.6 ms]
  Range (min … max):   249.7 ms … 255.7 ms    11 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum -a sm3 
  Time (mean ± σ):     363.9 ms ±   1.2 ms    [User: 386.8 ms, System: 147.8 ms]
  Range (min … max):   362.6 ms … 367.0 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum -a sm3  ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum -a sm3 
    1.34 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
    1.94 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum -a sm3 

-------------------------------- 4096 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha1sum 
 
  Warning:   Time (mean ± σ):      66.3 ms ±   0.6 ms    [User: 121.8 ms, System: 58.9 ms]
  Range (min … max):    65.6 ms …  68.4 ms    43 runs
Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha1sum 
  Time (mean ± σ):      63.3 ms ±   1.3 ms    [User: 122.9 ms, System: 61.6 ms]
  Range (min … max):    59.6 ms …  66.0 ms    45 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha1sum 
  Time (mean ± σ):      59.0 ms ±   0.3 ms    [User: 90.5 ms, System: 33.0 ms]
  Range (min … max):    58.5 ms …  59.6 ms    47 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha1sum 
  Time (mean ± σ):     223.3 ms ±   1.3 ms    [User: 283.9 ms, System: 175.6 ms]
  Range (min … max):   221.7 ms … 225.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha1sum  ran
    1.07 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha1sum 
    1.12 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha1sum 
    3.79 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha1sum 

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha256sum 
  Time (mean ± σ):      96.2 ms ±   0.6 ms    [User: 205.6 ms, System: 59.5 ms]
  Range (min … max):    95.6 ms …  99.1 ms    30 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha256sum 
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      91.3 ms ±   1.8 ms    [User: 206.1 ms, System: 63.1 ms]
  Range (min … max):    89.8 ms …  96.0 ms    30 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha256sum 
  Time (mean ± σ):      97.6 ms ±   0.7 ms    [User: 173.1 ms, System: 32.9 ms]
  Range (min … max):    96.4 ms … 100.7 ms    29 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha256sum 
  Time (mean ± σ):     229.2 ms ±   1.0 ms    [User: 371.0 ms, System: 173.4 ms]
  Range (min … max):   227.8 ms … 231.1 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha256sum  ran
    1.05 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha256sum 
    1.07 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha256sum 
    2.51 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha256sum 

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha512sum 
  Time (mean ± σ):      80.4 ms ±   0.6 ms    [User: 162.8 ms, System: 60.1 ms]
  Range (min … max):    79.6 ms …  82.5 ms    34 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha512sum 
  Time (mean ± σ):      76.4 ms ±   1.6 ms    [User: 164.7 ms, System: 62.0 ms]
  Range (min … max):    74.3 ms …  79.9 ms    38 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha512sum 
  Time (mean ± σ):      77.5 ms ±   0.2 ms    [User: 132.6 ms, System: 31.8 ms]
  Range (min … max):    77.1 ms …  78.2 ms    37 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha512sum 
  Time (mean ± σ):     223.1 ms ±   1.8 ms    [User: 329.1 ms, System: 173.9 ms]
  Range (min … max):   220.8 ms … 226.8 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha512sum  ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha512sum 
    1.05 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha512sum 
    2.92 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha512sum 

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha224sum 
  Time (mean ± σ):      95.9 ms ±   0.7 ms    [User: 203.2 ms, System: 61.0 ms]
  Range (min … max):    93.9 ms …  98.4 ms    30 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha224sum 
  Time (mean ± σ):      92.8 ms ±   2.4 ms    [User: 205.5 ms, System: 62.7 ms]
  Range (min … max):    89.7 ms …  96.6 ms    30 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha224sum 
  Time (mean ± σ):      97.1 ms ±   0.3 ms    [User: 171.0 ms, System: 34.1 ms]
  Range (min … max):    96.6 ms …  98.0 ms    29 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha224sum 
  Time (mean ± σ):     228.8 ms ±   1.2 ms    [User: 374.0 ms, System: 170.1 ms]
  Range (min … max):   227.3 ms … 232.0 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha224sum  ran
    1.03 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha224sum 
    1.05 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha224sum 
    2.47 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha224sum 

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha384sum 
  Time (mean ± σ):      79.7 ms ±   0.7 ms    [User: 160.2 ms, System: 59.3 ms]
  Range (min … max):    78.9 ms …  81.6 ms    35 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha384sum 
  Time (mean ± σ):      76.2 ms ±   1.7 ms    [User: 160.4 ms, System: 62.9 ms]
  Range (min … max):    74.1 ms …  79.3 ms    38 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha384sum 
  Time (mean ± σ):      76.1 ms ±   0.3 ms    [User: 126.8 ms, System: 34.3 ms]
  Range (min … max):    75.6 ms …  76.8 ms    37 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha384sum 
  Time (mean ± σ):     224.0 ms ±   1.7 ms    [User: 325.7 ms, System: 174.2 ms]
  Range (min … max):   221.9 ms … 227.7 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha384sum  ran
    1.00 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha384sum 
    1.05 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha384sum 
    2.94 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha384sum 

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- md5sum 
  Time (mean ± σ):      76.6 ms ±   0.7 ms    [User: 149.3 ms, System: 59.4 ms]
  Range (min … max):    75.9 ms …  78.8 ms    37 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- md5sum 
  Time (mean ± σ):      73.0 ms ±   1.7 ms    [User: 149.9 ms, System: 62.6 ms]
  Range (min … max):    68.5 ms …  76.4 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- md5sum 
  Time (mean ± σ):      71.9 ms ±   0.3 ms    [User: 119.1 ms, System: 31.8 ms]
  Range (min … max):    71.4 ms …  72.6 ms    39 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- md5sum 
  Time (mean ± σ):     223.2 ms ±   1.1 ms    [User: 318.3 ms, System: 169.7 ms]
  Range (min … max):   221.6 ms … 225.3 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- md5sum  ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- md5sum 
    1.07 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- md5sum 
    3.11 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- md5sum 

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -s 
  Time (mean ± σ):      44.4 ms ±   0.3 ms    [User: 59.8 ms, System: 57.0 ms]
  Range (min … max):    43.8 ms …  45.3 ms    62 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -s 
  Time (mean ± σ):      41.9 ms ±   0.5 ms    [User: 61.1 ms, System: 60.1 ms]
  Range (min … max):    41.4 ms …  43.7 ms    66 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -s 
  Time (mean ± σ):      30.6 ms ±   0.2 ms    [User: 30.6 ms, System: 32.6 ms]
  Range (min … max):    30.0 ms …  31.6 ms    87 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -s 
  Time (mean ± σ):     222.9 ms ±   2.3 ms    [User: 225.4 ms, System: 163.7 ms]
  Range (min … max):   220.6 ms … 229.0 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -s  ran
    1.37 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -s 
    1.45 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -s 
    7.28 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -s 

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -r 
  Time (mean ± σ):      77.3 ms ±   0.4 ms    [User: 148.3 ms, System: 58.4 ms]
  Range (min … max):    76.4 ms …  78.2 ms    37 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -r 
  Time (mean ± σ):      73.8 ms ±   1.4 ms    [User: 151.3 ms, System: 59.4 ms]
  Range (min … max):    71.9 ms …  76.5 ms    37 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -r 
  Time (mean ± σ):      72.1 ms ±   0.3 ms    [User: 118.8 ms, System: 32.4 ms]
  Range (min … max):    71.6 ms …  72.8 ms    39 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -r 
  Time (mean ± σ):     223.0 ms ±   1.2 ms    [User: 316.3 ms, System: 162.2 ms]
  Range (min … max):   219.8 ms … 225.4 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -r  ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -r 
    1.07 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -r 
    3.09 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -r 

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum 
  Time (mean ± σ):      41.9 ms ±   0.3 ms    [User: 53.1 ms, System: 58.9 ms]
  Range (min … max):    41.5 ms …  42.5 ms    65 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum 
  Time (mean ± σ):      40.0 ms ±   0.7 ms    [User: 53.6 ms, System: 62.3 ms]
  Range (min … max):    39.2 ms …  41.9 ms    68 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum 
  Time (mean ± σ):      27.2 ms ±   0.2 ms    [User: 22.9 ms, System: 32.6 ms]
  Range (min … max):    26.7 ms …  28.1 ms    98 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum 
  Time (mean ± σ):     224.6 ms ±   1.1 ms    [User: 223.4 ms, System: 170.4 ms]
  Range (min … max):   222.7 ms … 226.5 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum  ran
    1.47 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum 
    1.54 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum 
    8.27 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum 

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- b2sum 
  Time (mean ± σ):      75.4 ms ±   0.4 ms    [User: 147.9 ms, System: 56.6 ms]
  Range (min … max):    74.7 ms …  76.7 ms    37 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- b2sum 
  Time (mean ± σ):      71.3 ms ±   1.4 ms    [User: 149.5 ms, System: 59.0 ms]
  Range (min … max):    69.4 ms …  74.3 ms    38 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- b2sum 
  Time (mean ± σ):      70.6 ms ±   0.4 ms    [User: 114.6 ms, System: 34.5 ms]
  Range (min … max):    69.9 ms …  72.0 ms    40 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- b2sum 
  Time (mean ± σ):     224.1 ms ±   1.3 ms    [User: 312.6 ms, System: 164.4 ms]
  Range (min … max):   222.4 ms … 226.3 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- b2sum  ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- b2sum 
    1.07 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- b2sum 
    3.18 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- b2sum 

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum -a sm3 
 
  Warning  Time (mean ± σ):     142.7 ms ±   2.1 ms    [User: 335.1 ms, System: 60.0 ms]
  Range (min … max):   141.1 ms … 148.5 ms    20 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum -a sm3 
  Time (mean ± σ):     135.9 ms ±   2.5 ms    [User: 338.0 ms, System: 61.5 ms]
  Range (min … max):   132.9 ms … 140.7 ms    21 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
  Time (mean ± σ):     157.6 ms ±   0.9 ms    [User: 299.7 ms, System: 34.2 ms]
  Range (min … max):   156.9 ms … 160.7 ms    18 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum -a sm3 
  Time (mean ± σ):     268.3 ms ±   0.7 ms    [User: 507.3 ms, System: 167.7 ms]
  Range (min … max):   267.1 ms … 269.3 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum -a sm3  ran
    1.05 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum -a sm3 
    1.16 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
    1.97 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum -a sm3 

-------------------------------- 16384 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha1sum 
  Time (mean ± σ):     187.2 ms ±   0.5 ms    [User: 830.0 ms, System: 212.0 ms]
  Range (min … max):   186.2 ms … 188.2 ms    15 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha1sum 
  Time (mean ± σ):     195.4 ms ±  16.1 ms    [User: 924.6 ms, System: 238.4 ms]
  Range (min … max):   181.5 ms … 232.9 ms    16 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha1sum 
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     239.1 ms ±   2.9 ms    [User: 748.9 ms, System: 170.1 ms]
  Range (min … max):   237.6 ms … 248.0 ms    12 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha1sum 
  Time (mean ± σ):     470.2 ms ±   1.1 ms    [User: 1202.6 ms, System: 372.9 ms]
  Range (min … max):   468.7 ms … 472.8 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha1sum  ran
    1.04 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha1sum 
    1.28 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha1sum 
    2.51 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha1sum 

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha256sum 
  Time (mean ± σ):     331.8 ms ±   0.4 ms    [User: 1638.2 ms, System: 210.8 ms]
  Range (min … max):   331.4 ms … 332.4 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha256sum 
  Time (mean ± σ):     352.1 ms ±  25.3 ms    [User: 1791.5 ms, System: 242.7 ms]
  Range (min … max):   331.5 ms … 404.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha256sum 
  Time (mean ± σ):     467.0 ms ±   0.8 ms    [User: 1550.1 ms, System: 170.6 ms]
  Range (min … max):   465.5 ms … 468.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha256sum 
  Time (mean ± σ):     553.1 ms ±   1.8 ms    [User: 2032.2 ms, System: 375.6 ms]
  Range (min … max):   551.0 ms … 556.2 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha256sum  ran
    1.06 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha256sum 
    1.41 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha256sum 
    1.67 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha256sum 

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha512sum 
  Time (mean ± σ):     247.3 ms ±   0.3 ms    [User: 1185.4 ms, System: 215.5 ms]
  Range (min … max):   246.9 ms … 247.8 ms    11 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha512sum 
 
  Time (mean ± σ):     252.3 ms ±  14.1 ms    [User: 1327.0 ms, System: 237.1 ms]
  Range (min … max):   243.3 ms … 277.3 ms    12 runs
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha512sum 
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.  Time (mean ± σ):     332.7 ms ±   3.3 ms    [User: 1098.2 ms, System: 172.4 ms]
  Range (min … max):   330.8 ms … 342.1 ms    10 runs

 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha512sum 
  Time (mean ± σ):     501.8 ms ±   1.1 ms    [User: 1571.0 ms, System: 375.9 ms]
  Range (min … max):   499.9 ms … 503.7 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha512sum  ran
    1.02 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha512sum 
    1.35 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha512sum 
    2.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha512sum 

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha224sum 
  Time (mean ± σ):     331.6 ms ±   0.6 ms    [User: 1627.5 ms, System: 218.3 ms]
  Range (min … max):   330.7 ms … 332.7 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha224sum 
 
  Warning  Time (mean ± σ):     336.9 ms ±  13.3 ms    [User: 1808.8 ms, System: 231.5 ms]
  Range (min … max):   331.6 ms … 374.7 ms    10 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha224sum 
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     467.9 ms ±   4.4 ms    [User: 1549.8 ms, System: 169.9 ms]
  Range (min … max):   465.7 ms … 480.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha224sum 
  Time (mean ± σ):     552.4 ms ±   3.0 ms    [User: 2026.0 ms, System: 380.7 ms]
  Range (min … max):   549.7 ms … 557.3 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha224sum  ran
    1.02 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha224sum 
    1.41 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha224sum 
    1.67 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha224sum 

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha384sum 
  Time (mean ± σ):     246.1 ms ±   1.2 ms    [User: 1162.7 ms, System: 219.3 ms]
  Range (min … max):   244.9 ms … 249.5 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha384sum 
  Time (mean ± σ):     257.4 ms ±  15.6 ms    [User: 1301.0 ms, System: 233.4 ms]
  Range (min … max):   241.7 ms … 275.5 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha384sum 
  Time (mean ± σ):     330.4 ms ±   0.4 ms    [User: 1083.3 ms, System: 172.2 ms]
  Range (min … max):   329.8 ms … 331.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha384sum 
  Time (mean ± σ):     501.3 ms ±   2.6 ms    [User: 1559.3 ms, System: 372.2 ms]
  Range (min … max):   497.7 ms … 505.8 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha384sum  ran
    1.05 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha384sum 
    1.34 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha384sum 
    2.04 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha384sum 

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- md5sum 
  Time (mean ± σ):     236.5 ms ±   1.4 ms    [User: 1105.3 ms, System: 214.7 ms]
  Range (min … max):   234.8 ms … 240.4 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- md5sum 
  Time (mean ± σ):     234.3 ms ±   0.4 ms    [User: 1150.8 ms, System: 237.9 ms]
  Range (min … max):   233.7 ms … 234.9 ms    12 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- md5sum 
  Time (mean ± σ):     318.6 ms ±   0.7 ms    [User: 1022.4 ms, System: 172.3 ms]
  Range (min … max):   317.8 ms … 320.1 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- md5sum 
  Time (mean ± σ):     498.3 ms ±   2.4 ms    [User: 1500.6 ms, System: 364.5 ms]
  Range (min … max):   494.4 ms … 503.3 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- md5sum  ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- md5sum 
    1.36 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- md5sum 
    2.13 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- md5sum 

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -s 
  Time (mean ± σ):      81.3 ms ±   0.8 ms    [User: 229.8 ms, System: 217.1 ms]
  Range (min … max):    78.9 ms …  83.1 ms    35 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -s 
  Time (mean ± σ):      76.3 ms ±   3.1 ms    [User: 250.2 ms, System: 244.2 ms]
  Range (min … max):    71.9 ms …  80.7 ms    35 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -s 
  Time (mean ± σ):      68.6 ms ±   0.5 ms    [User: 162.3 ms, System: 163.9 ms]
  Range (min … max):    68.0 ms …  70.6 ms    41 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -s 
  Time (mean ± σ):     453.0 ms ±   6.0 ms    [User: 608.7 ms, System: 356.9 ms]
  Range (min … max):   445.9 ms … 468.3 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -s  ran
    1.11 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -s 
    1.19 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -s 
    6.60 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -s 

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -r 
  Time (mean ± σ):     239.0 ms ±   0.7 ms    [User: 1117.6 ms, System: 211.5 ms]
  Range (min … max):   238.0 ms … 240.9 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -r 
  Time (mean ± σ):     243.0 ms ±   6.4 ms    [User: 1159.9 ms, System: 231.6 ms]
  Range (min … max):   237.4 ms … 259.0 ms    12 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -r 
  Time (mean ± σ):     323.5 ms ±   0.5 ms    [User: 1036.7 ms, System: 171.5 ms]
  Range (min … max):   323.0 ms … 324.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -r 
  Time (mean ± σ):     500.1 ms ±   1.6 ms    [User: 1503.0 ms, System: 362.6 ms]
  Range (min … max):   496.5 ms … 502.5 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -r  ran
    1.02 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -r 
    1.35 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -r 
    2.09 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -r 

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum 
  Time (mean ± σ):      72.2 ms ±   0.8 ms    [User: 174.0 ms, System: 220.3 ms]
  Range (min … max):    69.4 ms …  73.8 ms    39 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum 
  Time (mean ± σ):      67.2 ms ±   2.6 ms    [User: 187.2 ms, System: 251.8 ms]
  Range (min … max):    64.2 ms …  76.1 ms    44 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum 
  Time (mean ± σ):      54.8 ms ±   0.4 ms    [User: 102.0 ms, System: 168.4 ms]
  Range (min … max):    54.2 ms …  56.1 ms    51 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum 
  Time (mean ± σ):     449.9 ms ±   2.7 ms    [User: 550.2 ms, System: 371.0 ms]
  Range (min … max):   445.4 ms … 453.6 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum  ran
    1.23 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum 
    1.32 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum 
    8.20 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum 

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- b2sum 
 
    Time (mean ± σ):     222.1 ms ±   2.4 ms    [User: 1041.0 ms, System: 210.2 ms]
  Range (min … max):   219.5 ms … 229.8 ms    13 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- b2sum 
 
  Warning:   Time (mean ± σ):     229.3 ms ±  13.8 ms    [User: 1152.0 ms, System: 232.6 ms]
  Range (min … max):   217.1 ms … 249.2 ms    13 runs
Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- b2sum 
  Time (mean ± σ):     292.1 ms ±   0.4 ms    [User: 957.1 ms, System: 167.8 ms]
  Range (min … max):   291.6 ms … 292.9 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- b2sum 
  Time (mean ± σ):     488.1 ms ±   2.1 ms    [User: 1420.5 ms, System: 359.1 ms]
  Range (min … max):   485.2 ms … 491.8 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- b2sum  ran
    1.03 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- b2sum 
    1.31 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- b2sum 
    2.20 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- b2sum 

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum -a sm3 
 
    Time (mean ± σ):     571.4 ms ±   0.8 ms    [User: 2912.2 ms, System: 216.1 ms]
  Range (min … max):   570.7 ms … 573.5 ms    10 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum -a sm3 
 
  Warning  Time (mean ± σ):     595.5 ms ±  33.7 ms    [User: 3217.2 ms, System: 236.9 ms]
  Range (min … max):   571.4 ms … 648.3 ms    10 runs
: The first benchmarking run for this command was significantly slower than the rest (648.3 ms). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
  Time (mean ± σ):     832.2 ms ±   1.9 ms    [User: 2836.3 ms, System: 165.2 ms]
  Range (min … max):   830.7 ms … 836.9 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum -a sm3 
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     771.3 ms ±   6.5 ms    [User: 3300.0 ms, System: 393.2 ms]
  Range (min … max):   767.6 ms … 789.7 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum -a sm3  ran
    1.04 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum -a sm3 
    1.35 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum -a sm3 
    1.46 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum -a sm3 

-------------------------------- 65536 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha1sum 
  Time (mean ± σ):     319.0 ms ±   3.2 ms    [User: 2694.2 ms, System: 718.2 ms]
  Range (min … max):   313.8 ms … 323.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha1sum 
  Time (mean ± σ):     304.0 ms ±  17.0 ms    [User: 4196.9 ms, System: 902.2 ms]
  Range (min … max):   280.2 ms … 329.2 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha1sum 
  Time (mean ± σ):     290.5 ms ±   8.9 ms    [User: 3750.6 ms, System: 732.6 ms]
  Range (min … max):   271.8 ms … 305.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha1sum 
  Time (mean ± σ):      1.364 s ±  0.009 s    [User: 3.855 s, System: 1.020 s]
  Range (min … max):    1.346 s …  1.373 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha1sum  ran
    1.05 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha1sum 
    1.10 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha1sum 
    4.70 ± 0.15 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha1sum 

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha256sum 
  Time (mean ± σ):     550.7 ms ±   2.7 ms    [User: 5234.8 ms, System: 715.4 ms]
  Range (min … max):   546.3 ms … 554.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha256sum 
  Time (mean ± σ):     532.3 ms ±  15.4 ms    [User: 8431.9 ms, System: 872.1 ms]
  Range (min … max):   508.9 ms … 557.2 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha256sum 
  Time (mean ± σ):     564.2 ms ±  11.5 ms    [User: 7969.1 ms, System: 712.6 ms]
  Range (min … max):   551.5 ms … 580.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha256sum 
  Time (mean ± σ):      1.439 s ±  0.005 s    [User: 6.439 s, System: 1.056 s]
  Range (min … max):    1.430 s …  1.447 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha256sum  ran
    1.03 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha256sum 
    1.06 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha256sum 
    2.70 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha256sum 

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha512sum 
  Time (mean ± σ):     422.5 ms ±   1.5 ms    [User: 3836.6 ms, System: 723.8 ms]
  Range (min … max):   419.7 ms … 425.2 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha512sum 
  Time (mean ± σ):     407.9 ms ±  14.7 ms    [User: 6239.5 ms, System: 886.3 ms]
  Range (min … max):   391.8 ms … 430.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha512sum 
  Time (mean ± σ):     419.7 ms ±  13.2 ms    [User: 5716.8 ms, System: 715.7 ms]
  Range (min … max):   402.4 ms … 439.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha512sum 
  Time (mean ± σ):      1.380 s ±  0.007 s    [User: 4.996 s, System: 1.052 s]
  Range (min … max):    1.366 s …  1.390 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha512sum  ran
    1.03 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha512sum 
    1.04 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha512sum 
    3.38 ± 0.12 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha512sum 

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha224sum 
  Time (mean ± σ):     550.7 ms ±   4.2 ms    [User: 5231.0 ms, System: 708.4 ms]
  Range (min … max):   544.2 ms … 556.7 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha224sum 
  Time (mean ± σ):     530.2 ms ±  28.7 ms    [User: 8419.6 ms, System: 870.1 ms]
  Range (min … max):   488.5 ms … 580.2 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha224sum 
  Time (mean ± σ):     555.0 ms ±  15.5 ms    [User: 7914.3 ms, System: 711.1 ms]
  Range (min … max):   522.5 ms … 578.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha224sum 
  Time (mean ± σ):      1.431 s ±  0.006 s    [User: 6.410 s, System: 1.057 s]
  Range (min … max):    1.423 s …  1.439 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha224sum  ran
    1.04 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha224sum 
    1.05 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha224sum 
    2.70 ± 0.15 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha224sum 

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha384sum 
  Time (mean ± σ):     417.4 ms ±   4.5 ms    [User: 3800.4 ms, System: 719.3 ms]
  Range (min … max):   411.7 ms … 426.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha384sum 
  Time (mean ± σ):     406.7 ms ±  17.0 ms    [User: 6141.7 ms, System: 877.9 ms]
  Range (min … max):   380.7 ms … 437.5 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha384sum 
  Time (mean ± σ):     405.4 ms ±  16.4 ms    [User: 5572.9 ms, System: 732.4 ms]
  Range (min … max):   375.8 ms … 432.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha384sum 
  Time (mean ± σ):      1.377 s ±  0.015 s    [User: 4.922 s, System: 1.061 s]
  Range (min … max):    1.354 s …  1.404 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha384sum  ran
    1.00 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha384sum 
    1.03 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha384sum 
    3.40 ± 0.14 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha384sum 

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- md5sum 
  Time (mean ± σ):     397.0 ms ±   1.7 ms    [User: 3526.3 ms, System: 720.8 ms]
  Range (min … max):   394.5 ms … 399.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- md5sum 
  Time (mean ± σ):     318.0 ms ±   5.7 ms    [User: 4143.5 ms, System: 916.9 ms]
  Range (min … max):   311.7 ms … 327.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- md5sum 
  Time (mean ± σ):     323.0 ms ±   9.7 ms    [User: 3849.0 ms, System: 742.2 ms]
  Range (min … max):   314.0 ms … 338.1 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- md5sum 
  Time (mean ± σ):      1.366 s ±  0.014 s    [User: 4.733 s, System: 1.026 s]
  Range (min … max):    1.357 s …  1.401 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- md5sum  ran
    1.02 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- md5sum 
    1.25 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- md5sum 
    4.30 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- md5sum 

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -s 
  Time (mean ± σ):     145.6 ms ±   1.1 ms    [User: 787.0 ms, System: 716.9 ms]
  Range (min … max):   144.0 ms … 148.1 ms    20 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -s 
  Time (mean ± σ):     128.7 ms ±   3.0 ms    [User: 1009.9 ms, System: 901.4 ms]
  Range (min … max):   123.2 ms … 136.0 ms    23 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -s 
  Time (mean ± σ):     113.8 ms ±   7.0 ms    [User: 678.2 ms, System: 683.9 ms]
  Range (min … max):   105.1 ms … 126.0 ms    24 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -s 
  Time (mean ± σ):      1.344 s ±  0.016 s    [User: 2.004 s, System: 0.980 s]
  Range (min … max):    1.331 s …  1.387 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -s  ran
    1.13 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -s 
    1.28 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -s 
   11.81 ± 0.74 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -s 

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -r 
  Time (mean ± σ):     399.1 ms ±   2.3 ms    [User: 3568.6 ms, System: 705.2 ms]
  Range (min … max):   394.5 ms … 401.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -r 
  Time (mean ± σ):     327.0 ms ±   8.3 ms    [User: 4229.4 ms, System: 867.4 ms]
  Range (min … max):   314.0 ms … 335.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -r 
  Time (mean ± σ):     328.2 ms ±  10.2 ms    [User: 3893.9 ms, System: 710.6 ms]
  Range (min … max):   315.0 ms … 342.7 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -r 
  Time (mean ± σ):      1.376 s ±  0.012 s    [User: 4.754 s, System: 1.019 s]
  Range (min … max):    1.352 s …  1.387 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -r  ran
    1.00 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -r 
    1.22 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -r 
    4.21 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -r 

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum 
  Time (mean ± σ):     132.4 ms ±   1.8 ms    [User: 599.6 ms, System: 732.6 ms]
  Range (min … max):   129.6 ms … 136.7 ms    21 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum 
  Time (mean ± σ):     119.6 ms ±   2.5 ms    [User: 718.0 ms, System: 880.0 ms]
  Range (min … max):   116.1 ms … 125.4 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum 
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.  Time (mean ± σ):      99.9 ms ±   3.8 ms    [User: 410.0 ms, System: 651.5 ms]
  Range (min … max):    97.9 ms … 113.2 ms    29 runs

 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum 
  Time (mean ± σ):      1.335 s ±  0.015 s    [User: 1.820 s, System: 0.996 s]
  Range (min … max):    1.319 s …  1.373 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum  ran
    1.20 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum 
    1.33 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum 
   13.37 ± 0.53 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum 

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- b2sum 
  Time (mean ± σ):     378.9 ms ±   3.0 ms    [User: 3398.0 ms, System: 689.7 ms]
  Range (min … max):   375.8 ms … 384.7 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- b2sum 
  Time (mean ± σ):     356.0 ms ±  18.3 ms    [User: 5265.8 ms, System: 883.2 ms]
  Range (min … max):   331.4 ms … 381.0 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- b2sum 
  Time (mean ± σ):     372.8 ms ±  10.1 ms    [User: 4811.9 ms, System: 719.7 ms]
  Range (min … max):   359.6 ms … 389.7 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- b2sum 
  Time (mean ± σ):      1.370 s ±  0.010 s    [User: 4.531 s, System: 1.012 s]
  Range (min … max):    1.361 s …  1.395 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- b2sum  ran
    1.05 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- b2sum 
    1.06 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- b2sum 
    3.85 ± 0.20 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- b2sum 

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum -a sm3 
  Time (mean ± σ):     926.1 ms ±   7.7 ms    [User: 9269.7 ms, System: 713.7 ms]
  Range (min … max):   918.7 ms … 945.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum -a sm3 
  Time (mean ± σ):     902.7 ms ±  29.1 ms    [User: 15647.2 ms, System: 868.2 ms]
  Range (min … max):   864.7 ms … 964.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
  Time (mean ± σ):     971.5 ms ±  18.9 ms    [User: 15030.5 ms, System: 734.3 ms]
  Range (min … max):   947.9 ms … 1013.9 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum -a sm3 
  Time (mean ± σ):      1.571 s ±  0.012 s    [User: 10.482 s, System: 1.077 s]
  Range (min … max):    1.556 s …  1.601 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum -a sm3  ran
    1.03 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum -a sm3 
    1.08 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
    1.74 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum -a sm3 

-------------------------------- 262144 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha1sum 
  Time (mean ± σ):      1.172 s ±  0.004 s    [User: 11.871 s, System: 2.913 s]
  Range (min … max):    1.165 s …  1.178 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha1sum 
  Time (mean ± σ):      1.123 s ±  0.019 s    [User: 19.531 s, System: 3.715 s]
  Range (min … max):    1.102 s …  1.171 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha1sum 
  Time (mean ± σ):      1.072 s ±  0.019 s    [User: 18.402 s, System: 3.238 s]
  Range (min … max):    1.041 s …  1.099 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha1sum 
  Time (mean ± σ):      5.221 s ±  0.054 s    [User: 16.168 s, System: 3.861 s]
  Range (min … max):    5.168 s …  5.347 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha1sum  ran
    1.05 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha1sum 
    1.09 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha1sum 
    4.87 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha1sum 

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha256sum 
  Time (mean ± σ):      2.079 s ±  0.007 s    [User: 23.328 s, System: 2.890 s]
  Range (min … max):    2.073 s …  2.093 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha256sum 
  Time (mean ± σ):      2.177 s ±  0.034 s    [User: 40.360 s, System: 3.560 s]
  Range (min … max):    2.145 s …  2.241 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha256sum 
  Time (mean ± σ):      2.106 s ±  0.030 s    [User: 38.968 s, System: 3.121 s]
  Range (min … max):    2.065 s …  2.144 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha256sum 
 
  Warning: The first benchmarking run for this command was significantly slower than the rest (5.751 s). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
  Time (mean ± σ):      5.556 s ±  0.074 s    [User: 27.818 s, System: 4.042 s]
  Range (min … max):    5.509 s …  5.751 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha256sum  ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha256sum 
    1.05 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha256sum 
    2.67 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha256sum 

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha512sum 
  Time (mean ± σ):      1.574 s ±  0.007 s    [User: 16.992 s, System: 2.894 s]
  Range (min … max):    1.568 s …  1.586 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha512sum 
  Time (mean ± σ):      1.576 s ±  0.017 s    [User: 29.430 s, System: 3.600 s]
  Range (min … max):    1.559 s …  1.617 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha512sum 
  Time (mean ± σ):      1.524 s ±  0.030 s    [User: 28.239 s, System: 3.173 s]
  Range (min … max):    1.493 s …  1.576 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha512sum 
  Time (mean ± σ):      5.377 s ±  0.031 s    [User: 21.284 s, System: 4.005 s]
  Range (min … max):    5.314 s …  5.408 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha512sum  ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha512sum 
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha512sum 
    3.53 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha512sum 

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha224sum 
  Time (mean ± σ):      2.074 s ±  0.004 s    [User: 23.302 s, System: 2.864 s]
  Range (min … max):    2.068 s …  2.078 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha224sum 
  Time (mean ± σ):      2.159 s ±  0.016 s    [User: 40.172 s, System: 3.548 s]
  Range (min … max):    2.142 s …  2.198 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha224sum 
  Time (mean ± σ):      2.112 s ±  0.035 s    [User: 38.834 s, System: 3.152 s]
  Range (min … max):    2.065 s …  2.165 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha224sum 
  Time (mean ± σ):      5.599 s ±  0.091 s    [User: 27.811 s, System: 4.047 s]
  Range (min … max):    5.476 s …  5.760 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha224sum  ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha224sum 
    1.04 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha224sum 
    2.70 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha224sum 

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha384sum 
  Time (mean ± σ):      1.557 s ±  0.004 s    [User: 16.758 s, System: 2.909 s]
  Range (min … max):    1.550 s …  1.565 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha384sum 
  Time (mean ± σ):      1.571 s ±  0.023 s    [User: 28.861 s, System: 3.599 s]
  Range (min … max):    1.548 s …  1.624 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha384sum 
  Time (mean ± σ):      1.529 s ±  0.031 s    [User: 27.765 s, System: 3.154 s]
  Range (min … max):    1.497 s …  1.590 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha384sum 
  Time (mean ± σ):      5.373 s ±  0.036 s    [User: 21.060 s, System: 3.997 s]
  Range (min … max):    5.309 s …  5.426 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha384sum  ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha384sum 
    1.03 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha384sum 
    3.51 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha384sum 

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- md5sum 
  Time (mean ± σ):      1.467 s ±  0.003 s    [User: 15.580 s, System: 2.901 s]
  Range (min … max):    1.462 s …  1.471 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- md5sum 
  Time (mean ± σ):      1.172 s ±  0.008 s    [User: 18.767 s, System: 3.708 s]
  Range (min … max):    1.163 s …  1.188 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- md5sum 
  Time (mean ± σ):      1.137 s ±  0.006 s    [User: 17.856 s, System: 3.258 s]
  Range (min … max):    1.124 s …  1.148 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- md5sum 
  Time (mean ± σ):      5.325 s ±  0.072 s    [User: 20.134 s, System: 3.924 s]
  Range (min … max):    5.268 s …  5.468 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- md5sum  ran
    1.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- md5sum 
    1.29 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- md5sum 
    4.68 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- md5sum 

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -s 
  Time (mean ± σ):     498.1 ms ±   2.3 ms    [User: 3313.4 ms, System: 2937.5 ms]
  Range (min … max):   495.0 ms … 501.2 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -s 
  Time (mean ± σ):     392.3 ms ±   1.3 ms    [User: 4290.6 ms, System: 3740.0 ms]
  Range (min … max):   390.4 ms … 393.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -s 
  Time (mean ± σ):     352.2 ms ±   8.0 ms    [User: 3112.3 ms, System: 3150.0 ms]
  Range (min … max):   342.3 ms … 361.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -s 
  Time (mean ± σ):      4.920 s ±  0.068 s    [User: 7.762 s, System: 3.663 s]
  Range (min … max):    4.872 s …  5.107 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -s  ran
    1.11 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -s 
    1.41 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -s 
   13.97 ± 0.37 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -s 

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -r 
  Time (mean ± σ):      1.486 s ±  0.004 s    [User: 15.875 s, System: 2.833 s]
  Range (min … max):    1.480 s …  1.491 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -r 
  Time (mean ± σ):      1.202 s ±  0.009 s    [User: 19.057 s, System: 3.559 s]
  Range (min … max):    1.188 s …  1.221 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -r 
  Time (mean ± σ):      1.156 s ±  0.015 s    [User: 18.009 s, System: 3.162 s]
  Range (min … max):    1.129 s …  1.179 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -r 
  Time (mean ± σ):      5.379 s ±  0.084 s    [User: 20.407 s, System: 3.845 s]
  Range (min … max):    5.306 s …  5.595 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -r  ran
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -r 
    1.29 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -r 
    4.65 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -r 

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum 
  Time (mean ± σ):     442.7 ms ±   1.7 ms    [User: 2509.5 ms, System: 2989.8 ms]
  Range (min … max):   441.1 ms … 445.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum 
  Time (mean ± σ):     378.1 ms ±   3.1 ms    [User: 2928.4 ms, System: 3514.2 ms]
  Range (min … max):   375.6 ms … 383.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum 
  Time (mean ± σ):     337.4 ms ±   2.6 ms    [User: 1769.6 ms, System: 2767.6 ms]
  Range (min … max):   333.7 ms … 340.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum 
 ⠦ Current estimate: 4.926 s      ███████████████████████████████████████████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ETA 00:00:40 ⠸ Current estimate: 4.931 s      ██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ETA 00:00:25 ⠙ Current estimate: 4.931 s      ██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ETA 00:00:26 ⠴ Current estimate: 4.931 s      ██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ETA 00:00:26 ⠧ Current estimate: 4.931 s      ██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ETA 00:00:27 ⠼ Current estimate: 4.931 s      ██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ETA 00:00:28 ⠼ Current estimate: 4.931 s      ██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ETA 00:00:30  Time (mean ± σ):      4.945 s ±  0.054 s    [User: 6.993 s, System: 3.732 s]
  Range (min … max):    4.881 s …  5.039 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum  ran
    1.12 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum 
    1.31 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum 
   14.66 ± 0.20 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum 

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- b2sum 
  Time (mean ± σ):      1.413 s ±  0.006 s    [User: 14.999 s, System: 2.854 s]
  Range (min … max):    1.401 s …  1.418 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- b2sum 
  Time (mean ± σ):      1.349 s ±  0.021 s    [User: 24.485 s, System: 3.541 s]
  Range (min … max):    1.330 s …  1.386 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- b2sum 
  Time (mean ± σ):      1.305 s ±  0.016 s    [User: 23.304 s, System: 3.162 s]
  Range (min … max):    1.274 s …  1.325 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- b2sum 
  Time (mean ± σ):      5.454 s ±  0.122 s    [User: 19.450 s, System: 3.941 s]
  Range (min … max):    5.292 s …  5.619 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- b2sum  ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- b2sum 
    1.08 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- b2sum 
    4.18 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- b2sum 

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum -a sm3 
 
    Time (mean ± σ):      3.525 s ±  0.027 s    [User: 41.485 s, System: 2.911 s]
  Range (min … max):    3.506 s …  3.600 s    10 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum -a sm3 
  Time (mean ± σ):      4.004 s ±  0.056 s    [User: 76.850 s, System: 3.617 s]
  Range (min … max):    3.951 s …  4.127 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
  Time (mean ± σ):      3.946 s ±  0.072 s    [User: 75.258 s, System: 3.198 s]
  Range (min … max):    3.833 s …  4.095 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum -a sm3 
 ⠇ Current estimate: 5.916 s      ██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░░ ETA 00:00:05
  Time (mean ± σ):      5.912 s ±  0.033 s    [User: 46.175 s, System: 4.116 s]
  Range (min … max):    5.876 s …  5.988 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum -a sm3  ran
    1.12 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
    1.14 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum -a sm3 
    1.68 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum -a sm3 

-------------------------------- 586011 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha1sum 
  Time (mean ± σ):      2.650 s ±  0.225 s    [User: 23.554 s, System: 5.206 s]
  Range (min … max):    2.392 s …  3.177 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha1sum 
  Time (mean ± σ):      3.121 s ±  0.020 s    [User: 39.968 s, System: 7.690 s]
  Range (min … max):    3.096 s …  3.157 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha1sum 
  Time (mean ± σ):      2.983 s ±  0.036 s    [User: 35.337 s, System: 6.590 s]
  Range (min … max):    2.923 s …  3.040 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha1sum 
  Time (mean ± σ):     12.487 s ±  0.209 s    [User: 35.757 s, System: 8.531 s]
  Range (min … max):   12.251 s … 12.829 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha1sum  ran
    1.13 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha1sum 
    1.18 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha1sum 
    4.71 ± 0.41 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha1sum 

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha256sum 
  Time (mean ± σ):      5.464 s ±  0.354 s    [User: 47.344 s, System: 4.994 s]
  Range (min … max):    4.586 s …  5.960 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha256sum 
  Time (mean ± σ):      6.198 s ±  0.083 s    [User: 81.300 s, System: 7.376 s]
  Range (min … max):    6.124 s …  6.411 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha256sum 
  Time (mean ± σ):      5.961 s ±  0.117 s    [User: 72.392 s, System: 6.431 s]
  Range (min … max):    5.836 s …  6.198 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha256sum 
  Time (mean ± σ):     12.700 s ±  0.157 s    [User: 60.158 s, System: 8.745 s]
  Range (min … max):   12.492 s … 12.956 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha256sum  ran
    1.09 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha256sum 
    1.13 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha256sum 
    2.32 ± 0.15 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha256sum 

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha512sum 
  Time (mean ± σ):      3.696 s ±  0.272 s    [User: 34.291 s, System: 5.157 s]
  Range (min … max):    3.312 s …  4.010 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha512sum 
  Time (mean ± σ):      4.412 s ±  0.034 s    [User: 60.002 s, System: 7.456 s]
  Range (min … max):    4.378 s …  4.476 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha512sum 
  Time (mean ± σ):      4.239 s ±  0.025 s    [User: 53.872 s, System: 6.465 s]
  Range (min … max):    4.211 s …  4.277 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha512sum 
  Time (mean ± σ):     12.593 s ±  0.140 s    [User: 46.407 s, System: 8.793 s]
  Range (min … max):   12.429 s … 12.797 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha512sum  ran
    1.15 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha512sum 
    1.19 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha512sum 
    3.41 ± 0.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha512sum 

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha224sum 
 
    Time (mean ± σ):      5.257 s ±  0.368 s    [User: 46.040 s, System: 5.167 s]
  Range (min … max):    4.560 s …  5.500 s    10 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha224sum 
  Time (mean ± σ):      6.193 s ±  0.068 s    [User: 80.706 s, System: 7.349 s]
  Range (min … max):    6.129 s …  6.344 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha224sum 
  Time (mean ± σ):      5.907 s ±  0.089 s    [User: 72.064 s, System: 6.396 s]
  Range (min … max):    5.816 s …  6.071 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha224sum 
  Time (mean ± σ):     12.767 s ±  0.207 s    [User: 60.161 s, System: 8.765 s]
  Range (min … max):   12.445 s … 13.146 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha224sum  ran
    1.12 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha224sum 
    1.18 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha224sum 
    2.43 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha224sum 

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha384sum 
  Time (mean ± σ):      3.743 s ±  0.208 s    [User: 33.804 s, System: 5.128 s]
  Range (min … max):    3.389 s …  3.959 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha384sum 
  Time (mean ± σ):      4.384 s ±  0.017 s    [User: 58.930 s, System: 7.436 s]
  Range (min … max):    4.352 s …  4.408 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha384sum 
  Time (mean ± σ):      4.250 s ±  0.071 s    [User: 52.722 s, System: 6.460 s]
  Range (min … max):    4.151 s …  4.369 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha384sum 
  Time (mean ± σ):     12.643 s ±  0.218 s    [User: 46.029 s, System: 8.754 s]
  Range (min … max):   12.345 s … 13.066 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha384sum  ran
    1.14 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha384sum 
    1.17 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha384sum 
    3.38 ± 0.20 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha384sum 

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- md5sum 
  Time (mean ± σ):      3.301 s ±  0.349 s    [User: 27.291 s, System: 5.321 s]
  Range (min … max):    2.806 s …  3.745 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- md5sum 
  Time (mean ± σ):      3.589 s ±  0.023 s    [User: 39.582 s, System: 7.725 s]
  Range (min … max):    3.564 s …  3.643 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- md5sum 
  Time (mean ± σ):      3.529 s ±  0.035 s    [User: 36.620 s, System: 6.709 s]
  Range (min … max):    3.497 s …  3.615 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- md5sum 
  Time (mean ± σ):     12.623 s ±  0.282 s    [User: 44.137 s, System: 8.641 s]
  Range (min … max):   12.356 s … 13.231 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- md5sum  ran
    1.07 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- md5sum 
    1.09 ± 0.12 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- md5sum 
    3.82 ± 0.41 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- md5sum 

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -s 
  Time (mean ± σ):     946.9 ms ±  30.3 ms    [User: 6192.1 ms, System: 5105.8 ms]
  Range (min … max):   892.9 ms … 1004.5 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -s 
  Time (mean ± σ):     880.1 ms ±  19.2 ms    [User: 9063.0 ms, System: 7387.4 ms]
  Range (min … max):   857.2 ms … 916.8 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -s 
  Time (mean ± σ):     835.5 ms ±  19.2 ms    [User: 6491.2 ms, System: 6266.6 ms]
  Range (min … max):   815.5 ms … 867.5 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -s 
  Time (mean ± σ):     11.550 s ±  0.134 s    [User: 17.388 s, System: 7.905 s]
  Range (min … max):   11.426 s … 11.825 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -s  ran
    1.05 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -s 
    1.13 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -s 
   13.82 ± 0.36 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -s 

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -r 
  Time (mean ± σ):      3.466 s ±  0.373 s    [User: 28.272 s, System: 5.133 s]
  Range (min … max):    2.894 s …  3.940 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -r 
  Time (mean ± σ):      3.666 s ±  0.030 s    [User: 40.234 s, System: 7.339 s]
  Range (min … max):    3.619 s …  3.731 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -r 
  Time (mean ± σ):      3.611 s ±  0.036 s    [User: 37.093 s, System: 6.408 s]
  Range (min … max):    3.585 s …  3.710 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -r 
  Time (mean ± σ):     12.640 s ±  0.225 s    [User: 44.532 s, System: 8.468 s]
  Range (min … max):   12.426 s … 13.070 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -r  ran
    1.04 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -r 
    1.06 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -r 
    3.65 ± 0.40 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -r 

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum 
  Time (mean ± σ):     829.6 ms ±   3.7 ms    [User: 4685.5 ms, System: 5284.5 ms]
  Range (min … max):   823.2 ms … 833.5 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum 
  Time (mean ± σ):     791.9 ms ±  13.4 ms    [User: 6308.2 ms, System: 7165.9 ms]
  Range (min … max):   778.0 ms … 825.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum 
  Time (mean ± σ):     738.4 ms ±   7.3 ms    [User: 3848.6 ms, System: 5818.8 ms]
  Range (min … max):   725.1 ms … 752.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum 
  Time (mean ± σ):     11.540 s ±  0.229 s    [User: 15.706 s, System: 7.997 s]
  Range (min … max):   11.298 s … 11.911 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum  ran
    1.07 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum 
    1.12 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum 
   15.63 ± 0.35 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum 

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- b2sum 
  Time (mean ± σ):      3.365 s ±  0.131 s    [User: 29.783 s, System: 5.008 s]
  Range (min … max):    3.022 s …  3.496 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- b2sum 
  Time (mean ± σ):      3.785 s ±  0.048 s    [User: 50.293 s, System: 7.377 s]
  Range (min … max):    3.750 s …  3.890 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- b2sum 
  Time (mean ± σ):      3.653 s ±  0.043 s    [User: 45.695 s, System: 6.507 s]
  Range (min … max):    3.610 s …  3.731 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- b2sum 
  Time (mean ± σ):     12.777 s ±  0.260 s    [User: 42.295 s, System: 8.619 s]
  Range (min … max):   12.420 s … 13.074 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- b2sum  ran
    1.09 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- b2sum 
    1.12 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- b2sum 
    3.80 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- b2sum 

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum -a sm3 
  Time (mean ± σ):     10.088 s ±  0.969 s    [User: 85.205 s, System: 5.225 s]
  Range (min … max):    8.207 s … 11.819 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum -a sm3 
  Time (mean ± σ):     11.291 s ±  0.117 s    [User: 150.563 s, System: 7.487 s]
  Range (min … max):   11.162 s … 11.549 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
  Time (mean ± σ):     10.895 s ±  0.148 s    [User: 135.065 s, System: 6.612 s]
  Range (min … max):   10.692 s … 11.115 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum -a sm3 
  Time (mean ± σ):     14.682 s ±  0.123 s    [User: 100.242 s, System: 9.225 s]
  Range (min … max):   14.497 s … 14.918 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum -a sm3  ran
    1.08 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum -a sm3 
    1.12 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum -a sm3 
    1.46 ± 0.14 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum -a sm3 

-----------------------------------------------------
-------------------- "min" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0725492806    0.0721207206    0.0781548736    0.1972607006    0.1172719059    0.1157694039    0.1441136609    0.2617554599    0.0906274924    0.0900329534    0.1062718834    0.2244290244    0.1167222581    0.1163846021    0.1440623811    0.2613061681    0.0902456485    0.0896532325    0.1055503405    0.2236302745        0.0884230074    0.0880427944    0.1012558844    0.2193179074    0.0379575495    0.0371368735    0.0281982385    0.1733042825    0.0895200012    0.0884287402    0.1020563392    0.2210537302    0.0353550997    0.0354245297    0.0240985227    0.1731633677    0.0829882473    0.0817970883    0.09435617330.2127258993    0.1883521704    0.1864428494    0.2497440834    0.3626061574
4096    0.0655768109    0.0596105549    0.0585017389    0.2216701939    0.0955927409    0.0897772289    0.0964031809    0.2277729509    0.0796468713    0.0743361493    0.0770897793    0.2208075373    0.0938810896    0.0897425016    0.0965962096    0.2273142946    0.0788696839    0.0741393609    0.0756005169    0.2219480139        0.0759148604    0.0685203044    0.0713976994    0.2215595494    0.0438130551    0.0413726091    0.0300236861    0.2205559771    0.0764211859    0.0719333039    0.0715609039    0.2198399959    0.0414534216    0.0391596506    0.0267439386    0.2226973396    0.0747200568    0.0694276518    0.06992144980.2223807608    0.1411347168    0.1328836638    0.1569497788    0.2670658188
16384   0.1862010708    0.1815476478    0.2376147958    0.4686862118    0.3313501761    0.3315144501    0.4655262351    0.5509828511    0.2468590650    0.2432639230    0.3308469650    0.4999315320    0.3306703971    0.3315730251    0.4656507241    0.5496882461    0.2448745102    0.2416838862    0.3298178112    0.4976690792        0.2347731864    0.2336758484    0.3178289374    0.4944391134    0.0789190832    0.0718534232    0.0679940302    0.4459001922    0.2380091603    0.2374267823    0.3229949843    0.4965344523    0.0694431120    0.0642084890    0.0541962400    0.4453866420    0.2195185215    0.2170754415    0.29164267950.4852270675    0.5707129279    0.5713785259    0.8307220149    0.7675942029
65536   0.3137923634    0.2802067624    0.2718097804    1.3463057174    0.5462589237    0.5088761977    0.5515010727    1.4303588137    0.4197462099    0.3917511729    0.4023617669    1.3662735019    0.5441793706    0.4885483496    0.5224883406    1.4230513056    0.4116885937    0.3807410067    0.3757560897    1.3539447107        0.3945124253    0.3117381363    0.3140461933    1.3567777793    0.1439992672    0.1232170223    0.1050891893    1.3311445783    0.3944874952    0.3140057432    0.3149542022    1.3521522182    0.1296493026    0.1161085216    0.0978618486    1.3188973316    0.3757675170    0.3313534450    0.35956453801.3610394080    0.9187205544    0.8646857924    0.9479366124    1.5559927104
262144  1.1648061693    1.1017232723    1.0406766473    5.1681688363    2.0726582341    2.1450358941    2.0654615951    5.5087161911    1.5675671371    1.5594405201    1.4927170151    5.3139404321    2.0681154395    2.1416450345    2.0648643615    5.4762717785    1.5502969496    1.5481001986    1.4966613576    5.3086607006        1.4617856570    1.1632823990    1.1239862470    5.2683796680    0.4950119613    0.3903789713    0.3423145393    4.8723475693    1.4801376009    1.1883115719    1.1286273869    5.3061745149    0.4410655173    0.3756388113    0.3337273773    4.8811059413    1.4007820522    1.3300329712    1.27390869425.2924925582    3.5062176555    3.9506480065    3.8330923585    5.8760088905
586011  2.3923136934    3.0955043614    2.9231254404    12.250675349    4.5863840096    6.1235295356    5.8362190136    12.491693773    3.3121912227    4.3778836757    4.2106053027    12.428816722    4.5604190982    6.1289789822    5.8156796252    12.445419867    3.3890097998    4.3521584518    4.1510748128    12.345286059        2.8056101675    3.5637368165    3.4967733665    12.356047870    0.8929091068    0.8572040268    0.8154691408    11.426094993    2.8937127531    3.6189708691    3.5849237681    12.425836067    0.8232191540    0.7780309190    0.7251467810    11.298332261    3.0218262456    3.7496877696    3.609687861612.419755309    8.2065783868    11.162108993    10.691508801    14.496839781

-----------------------------------------------------
-------------------- "mean" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0730199223    0.0727325295    0.0788387873    0.1988198324    0.1179166227    0.1169469997    0.1453253860    0.2626935533    0.0915410373    0.0906715532    0.1070320217    0.2250823706    0.1178659428    0.1171349397    0.1448116400    0.2622763718    0.0910789308    0.0906048122    0.1062689514    0.2246542407        0.0889779443    0.0886569425    0.1020857566    0.2207526761    0.0383028472    0.0374748416    0.0290174489    0.1744665618    0.0902066171    0.0891769129    0.1026726891    0.2219749153    0.0356710583    0.0357798832    0.0246473490    0.1750061148    0.0837608943    0.0826988883    0.09508166970.2136881152    0.1893021058    0.187183433,    0.2507128390    0.3638964215
4096    0.0662833063    0.0632760842    0.0589545516    0.2233398189    0.0962282377    0.0912562797    0.0975668064    0.2292273993    0.0803544374    0.0763954230    0.0775014432    0.2230776096    0.0958628331    0.0928108339    0.0971468941    0.2288413843    0.0796613462    0.0761768973    0.0761303493    0.2239518882        0.0765774026    0.0729711427    0.0718783625    0.2232125049    0.0443525703    0.0419162273    0.0306106948    0.2229298717    0.0773298758    0.0738068019    0.0721446199    0.2229923810    0.0418869405    0.0400361401    0.0271546843    0.2246220423    0.0753970370    0.0712649086    0.07058350320.2241491358    0.1426924009    0.1359349092    0.1576450212    0.2682661666
16384   0.1871980125    0.1953725310    0.2390935907    0.4701749967    0.3317699046    0.3520922017    0.4670034138    0.5531233670    0.2473241606    0.2522944473    0.3327262876    0.5018026308    0.3315550050    0.3369232047    0.4678773355    0.5524455734    0.2460660748    0.2573758285    0.3304029292    0.5013195159        0.2364556890    0.2343003864    0.3186284278    0.4982938065    0.0813045957    0.0762675089    0.0686092018    0.4530062286    0.2389671540    0.2430036246    0.3235382090    0.5000614204    0.0722174997    0.0672379463    0.0548361801    0.4499172810    0.2221200837    0.2292743105    0.29207051840.4881344436    0.5713973304    0.5955244115    0.8322267957    0.7712735605
65536   0.3190217430    0.3039686247    0.2904862578    1.3643758421    0.5506981352    0.5322602172    0.5641757839    1.4389663410    0.4225085182    0.4078621635    0.4197106016    1.3804327243    0.5507408828    0.5301800463    0.5550237665    1.4306294011    0.4173711939    0.4066688335    0.4053551171    1.3766898245        0.3969684337    0.3179732961    0.3229690443    1.3663008127    0.1456421527    0.1287036576    0.1137885420    1.344100345,    0.3991115828    0.3269649010    0.3282313896    1.3756332228    0.1323509487    0.1196498197    0.0998527926    1.3353636497    0.3789085622    0.3560124901    0.37279929931.3703080622    0.9261403395    0.9026937788    0.9715127202    1.5708652400
262144  1.1716636143    1.1227816611    1.0716480678    5.2214036719    2.0793851362    2.1770797022    2.1064591426    5.5558967093    1.5744941511    1.5757496834    1.5239974325    5.3766309957    2.0739516322    2.1589828112    2.1116602555    5.5990196695    1.5566692385    1.5706978077    1.5290514212    5.3729022785        1.4668794246    1.1723651055    1.1365918910    5.3246280195    0.4980720323    0.3922736551    0.3521903143    4.9202543987    1.4861125105    1.2016379660    1.1555746630    5.3789883243    0.4427048144    0.3781248726    0.3373868298    4.9451578096    1.4134935179    1.3489518396    1.30452773425.4539864911    3.5246299047    4.004003121,    3.9460530153    5.9123989889
586011  2.6497735473    3.1213456798    2.9833969183    12.486515358    5.4643695951    6.1982650898    5.9606813089    12.700176593    3.6959487322    4.4118286994    4.2385404680    12.593050225    5.2574896882    6.1934049415    5.9074818364    12.767211230    3.7434766256    4.3843723871    4.2503598377    12.642655356        3.3010062543    3.5892329738    3.5287642209    12.623138410    0.9469379107    0.8801419148    0.8354571413    11.549625763    3.4662771444    3.6659014289    3.6111428259    12.640306087    0.8296444603    0.7918990211    0.7384492966    11.539809791    3.3645041315    3.7847914805    3.653322330412.777252783    10.088311143    11.291428700    10.895411649    14.681539787

-----------------------------------------------------
-------------------- "max" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0747662626    0.0741615886    0.0804643646    0.2021937996    0.1193425189    0.1189540589    0.1471742469    0.2635520749    0.0935937524    0.0919326634    0.1089844274    0.2260881664    0.1209736511    0.1182471311    0.1455510611    0.2632226401    0.0918952935    0.0920890625    0.1079752685    0.2261615185        0.0898324054    0.0901070724    0.1052970934    0.2216311354    0.0390476935    0.0382710505    0.0296965015    0.1770656874    0.0911271282    0.0899634162    0.1032894292    0.2238263312    0.0363411067    0.0361660467    0.0256898657    0.1769410617    0.0850851603    0.0849649253    0.09620375630.2146407543    0.1950043534    0.1879080674    0.2556889264    0.3670459814
4096    0.0684054459    0.0660460119    0.0595663249    0.2258932639    0.0990707199    0.0959664969    0.1006932339    0.2311182979    0.0825148173    0.0798570753    0.0781514703    0.2267763243    0.0984238326    0.0966344876    0.0980470316    0.2320282966    0.0816034609    0.0792983029    0.0767948729    0.2277424889        0.0788202144    0.0763762334    0.0725958374    0.2252927594    0.0452699571    0.0437250281    0.0316327341    0.2289844461    0.0781987559    0.0765269789    0.0728197419    0.2253638539    0.0425489726    0.0419314916    0.0281432956    0.2264767476    0.0767061178    0.0743164328    0.07203528380.2262995978    0.1485349998    0.1406588978    0.1606723698    0.2692751628
16384   0.1881756798    0.2328619948    0.2480400208    0.4727704738    0.3324143201    0.4043892301    0.4685933911    0.5562172361    0.2478273790    0.2772785350    0.3420665740    0.5036754060    0.3327318451    0.3747108331    0.4802625541    0.5572750881    0.2495044932    0.2754626782    0.3309527322    0.5057889982        0.2404480784    0.2348999594    0.3200814374    0.5032698624    0.0831384272    0.0807105332    0.0705756942    0.4682871592    0.2409402783    0.2590441453    0.3243063043    0.5025207933    0.0738424630    0.0761459610    0.0560836430    0.4536341710    0.2298145845    0.2492499585    0.29288736050.4918183375    0.5735202879    0.6482967529    0.8368970379    0.7896704729
65536   0.3238246434    0.3291922254    0.3050299444    1.3732451804    0.5541461517    0.5572447887    0.5804393237    1.4468459627    0.4252242999    0.4308585499    0.4390087729    1.3899137599    0.5567095036    0.5802244576    0.5785518606    1.4393770296    0.4260616737    0.4375480117    0.4320432467    1.4039422057        0.3997590453    0.3276198153    0.3380908893    1.4007709363    0.1481015383    0.1360332313    0.1260412803    1.3872137213    0.4017877972    0.3356740212    0.3427394602    1.3871537512    0.1366517846    0.1254419266    0.1132417966    1.3729799536    0.3847116680    0.3810268220    0.38965612501.3947641050    0.9457760924    0.9644108434    1.0138921534    1.6005561224
262144  1.1779748903    1.1710810003    1.0987153813    5.3473887253    2.0925728921    2.2409613151    2.1435633721    5.7509882371    1.5864084531    1.6171480191    1.5761458371    5.4083012591    2.0781124925    2.1982563185    2.1651579515    5.7604163735    1.5651364836    1.6240650556    1.5903365846    5.4262103166        1.4714459600    1.1875178940    1.1477677460    5.4675419580    0.5011934363    0.3938769363    0.3616323763    5.1065342913    1.4905707219    1.2214989189    1.1794270639    5.5949397999    0.4450970683    0.3835709303    0.3403238583    5.0393971113    1.4183179222    1.3858381572    1.32514034625.6188783932    3.5996732185    4.1272219795    4.0946580415    5.9881177885
586011  3.1771275914    3.1568401274    3.0397114554    12.828678901    5.9595992636    6.4107886896    6.1982562946    12.955663727    4.0101786267    4.4758234517    4.2770616137    12.796848963    5.5002785642    6.3437907212    6.0712895352    13.145722513    3.9587113318    4.4076030938    4.3693642108    13.066236158        3.7450412865    3.6432039595    3.6148728485    13.231045122    1.0045072648    0.9168488778    0.8674507488    11.825491057    3.9398605161    3.7311397151    3.7096188631    13.070390586    0.8334797400    0.8259179640    0.7525800050    11.911158419    3.4958889386    3.8903608146    3.731416718613.074085889    11.818628142    11.549276157    11.114704152    14.917738684


||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0730199223    0.0727325295    0.0788387873    0.1988198324    forkrun is 8.395% faster than xargs (1.0839x)   forkrun is 173.3% faster than parallel (2.7335x)
sha256sum       0.1179166227    0.1169469997    0.1453253860    0.2626935533    forkrun is 24.26% faster than xargs (1.2426x)   forkrun is 124.6% faster than parallel (2.2462x)
sha512sum       0.0915410373    0.0906715532    0.1070320217    0.2250823706    forkrun is 18.04% faster than xargs (1.1804x)   forkrun is 148.2% faster than parallel (2.4823x)
sha224sum       0.1178659428    0.1171349397    0.1448116400    0.2622763718    forkrun is 23.62% faster than xargs (1.2362x)   forkrun is 123.9% faster than parallel (2.2390x)
sha384sum       0.0910789308    0.0906048122    0.1062689514    0.2246542407    forkrun is 17.28% faster than xargs (1.1728x)   forkrun is 147.9% faster than parallel (2.4794x)
md5sum          0.0889779443    0.0886569425    0.1020857566    0.2207526761    forkrun is 14.73% faster than xargs (1.1473x)   forkrun is 148.0% faster than parallel (2.4809x)
sum -s          0.0383028472    0.0374748416    0.0290174489    0.1744665618    xargs is 29.14% faster than forkrun (1.2914x)   forkrun is 365.5% faster than parallel (4.6555x)
sum -r          0.0902066171    0.0891769129    0.1026726891    0.2219749153    forkrun is 15.13% faster than xargs (1.1513x)   forkrun is 148.9% faster than parallel (2.4891x)
cksum           0.0356710583    0.0357798832    0.0246473490    0.1750061148    xargs is 44.72% faster than forkrun (1.4472x)   forkrun is 390.6% faster than parallel (4.9061x)
b2sum           0.0837608943    0.0826988883    0.0950816697    0.2136881152    forkrun is 14.97% faster than xargs (1.1497x)   forkrun is 158.3% faster than parallel (2.5839x)
cksum -a sm3    0.1893021058    0.187183433     0.2507128390    0.3638964215    forkrun is 33.93% faster than xargs (1.3393x)   forkrun is 94.40% faster than parallel (1.9440x)

OVERALL         1.0176439232    1.0090617364    1.1864945392    2.5433111740    forkrun is 17.58% faster than xargs (1.1758x)   forkrun is 152.0% faster than parallel (2.5204x)




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0662833063    0.0632760842    0.0589545516    0.2233398189    xargs is 7.330% faster than forkrun (1.0733x)   forkrun is 252.9% faster than parallel (3.5296x)
sha256sum       0.0962282377    0.0912562797    0.0975668064    0.2292273993    forkrun is 1.391% faster than xargs (1.0139x)   forkrun is 138.2% faster than parallel (2.3821x)
sha512sum       0.0803544374    0.0763954230    0.0775014432    0.2230776096    forkrun is 1.447% faster than xargs (1.0144x)   forkrun is 192.0% faster than parallel (2.9200x)
sha224sum       0.0958628331    0.0928108339    0.0971468941    0.2288413843    forkrun is 4.671% faster than xargs (1.0467x)   forkrun is 146.5% faster than parallel (2.4656x)
sha384sum       0.0796613462    0.0761768973    0.0761303493    0.2239518882    xargs is .0611% faster than forkrun (1.0006x)   forkrun is 193.9% faster than parallel (2.9398x)
md5sum          0.0765774026    0.0729711427    0.0718783625    0.2232125049    xargs is 1.520% faster than forkrun (1.0152x)   forkrun is 205.8% faster than parallel (3.0589x)
sum -s          0.0443525703    0.0419162273    0.0306106948    0.2229298717    xargs is 36.93% faster than forkrun (1.3693x)   forkrun is 431.8% faster than parallel (5.3184x)
sum -r          0.0773298758    0.0738068019    0.0721446199    0.2229923810    xargs is 2.303% faster than forkrun (1.0230x)   forkrun is 202.1% faster than parallel (3.0212x)
cksum           0.0418869405    0.0400361401    0.0271546843    0.2246220423    xargs is 54.25% faster than forkrun (1.5425x)   forkrun is 436.2% faster than parallel (5.3625x)
b2sum           0.0753970370    0.0712649086    0.0705835032    0.2241491358    xargs is .9653% faster than forkrun (1.0096x)   forkrun is 214.5% faster than parallel (3.1452x)
cksum -a sm3    0.1426924009    0.1359349092    0.1576450212    0.2682661666    forkrun is 10.47% faster than xargs (1.1047x)   forkrun is 88.00% faster than parallel (1.8800x)

OVERALL         .87662638830    .83584564836    .83731693081    2.5146102031    forkrun is .1760% faster than xargs (1.0017x)   forkrun is 200.8% faster than parallel (3.0084x)




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.1871980125    0.1953725310    0.2390935907    0.4701749967    forkrun is 27.72% faster than xargs (1.2772x)   forkrun is 151.1% faster than parallel (2.5116x)
sha256sum       0.3317699046    0.3520922017    0.4670034138    0.5531233670    forkrun is 32.63% faster than xargs (1.3263x)   forkrun is 57.09% faster than parallel (1.5709x)
sha512sum       0.2473241606    0.2522944473    0.3327262876    0.5018026308    forkrun is 34.53% faster than xargs (1.3453x)   forkrun is 102.8% faster than parallel (2.0289x)
sha224sum       0.3315550050    0.3369232047    0.4678773355    0.5524455734    forkrun is 38.86% faster than xargs (1.3886x)   forkrun is 63.96% faster than parallel (1.6396x)
sha384sum       0.2460660748    0.2573758285    0.3304029292    0.5013195159    forkrun is 28.37% faster than xargs (1.2837x)   forkrun is 94.78% faster than parallel (1.9478x)
md5sum          0.2364556890    0.2343003864    0.3186284278    0.4982938065    forkrun is 35.99% faster than xargs (1.3599x)   forkrun is 112.6% faster than parallel (2.1267x)
sum -s          0.0813045957    0.0762675089    0.0686092018    0.4530062286    xargs is 11.16% faster than forkrun (1.1116x)   forkrun is 493.9% faster than parallel (5.9397x)
sum -r          0.2389671540    0.2430036246    0.3235382090    0.5000614204    forkrun is 35.39% faster than xargs (1.3539x)   forkrun is 109.2% faster than parallel (2.0925x)
cksum           0.0722174997    0.0672379463    0.0548361801    0.4499172810    xargs is 22.61% faster than forkrun (1.2261x)   forkrun is 569.1% faster than parallel (6.6914x)
b2sum           0.2221200837    0.2292743105    0.2920705184    0.4881344436    forkrun is 31.49% faster than xargs (1.3149x)   forkrun is 119.7% faster than parallel (2.1976x)
cksum -a sm3    0.5713973304    0.5955244115    0.8322267957    0.7712735605    forkrun is 45.64% faster than xargs (1.4564x)   forkrun is 34.98% faster than parallel (1.3498x)

OVERALL         2.7663755105    2.8396664017    3.7270128900    5.7395528247    forkrun is 34.72% faster than xargs (1.3472x)   forkrun is 107.4% faster than parallel (2.0747x)




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.3190217430    0.3039686247    0.2904862578    1.3643758421    xargs is 4.641% faster than forkrun (1.0464x)   forkrun is 348.8% faster than parallel (4.4885x)
sha256sum       0.5506981352    0.5322602172    0.5641757839    1.4389663410    forkrun is 5.996% faster than xargs (1.0599x)   forkrun is 170.3% faster than parallel (2.7035x)
sha512sum       0.4225085182    0.4078621635    0.4197106016    1.3804327243    xargs is .6666% faster than forkrun (1.0066x)   forkrun is 226.7% faster than parallel (3.2672x)
sha224sum       0.5507408828    0.5301800463    0.5550237665    1.4306294011    forkrun is .7776% faster than xargs (1.0077x)   forkrun is 159.7% faster than parallel (2.5976x)
sha384sum       0.4173711939    0.4066688335    0.4053551171    1.3766898245    xargs is .3240% faster than forkrun (1.0032x)   forkrun is 238.5% faster than parallel (3.3852x)
md5sum          0.3969684337    0.3179732961    0.3229690443    1.3663008127    xargs is 22.91% faster than forkrun (1.2291x)   forkrun is 244.1% faster than parallel (3.4418x)
sum -s          0.1456421527    0.1287036576    0.1137885420    1.344100345     xargs is 13.10% faster than forkrun (1.1310x)   forkrun is 944.3% faster than parallel (10.443x)
sum -r          0.3991115828    0.3269649010    0.3282313896    1.3756332228    xargs is 21.59% faster than forkrun (1.2159x)   forkrun is 244.6% faster than parallel (3.4467x)
cksum           0.1323509487    0.1196498197    0.0998527926    1.3353636497    xargs is 19.82% faster than forkrun (1.1982x)   forkrun is 1016.% faster than parallel (11.160x)
b2sum           0.3789085622    0.3560124901    0.3727992993    1.3703080622    xargs is 1.638% faster than forkrun (1.0163x)   forkrun is 261.6% faster than parallel (3.6164x)
cksum -a sm3    0.9261403395    0.9026937788    0.9715127202    1.5708652400    forkrun is 7.623% faster than xargs (1.0762x)   forkrun is 74.01% faster than parallel (1.7401x)

OVERALL         4.6394624932    4.3329378289    4.4439053153    15.353665465    forkrun is 2.561% faster than xargs (1.0256x)   forkrun is 254.3% faster than parallel (3.5434x)




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         1.1716636143    1.1227816611    1.0716480678    5.2214036719    xargs is 9.332% faster than forkrun (1.0933x)   forkrun is 345.6% faster than parallel (4.4564x)
sha256sum       2.0793851362    2.1770797022    2.1064591426    5.5558967093    forkrun is 1.302% faster than xargs (1.0130x)   forkrun is 167.1% faster than parallel (2.6718x)
sha512sum       1.5744941511    1.5757496834    1.5239974325    5.3766309957    xargs is 3.395% faster than forkrun (1.0339x)   forkrun is 241.2% faster than parallel (3.4121x)
sha224sum       2.0739516322    2.1589828112    2.1116602555    5.5990196695    forkrun is 1.818% faster than xargs (1.0181x)   forkrun is 169.9% faster than parallel (2.6996x)
sha384sum       1.5566692385    1.5706978077    1.5290514212    5.3729022785    xargs is 1.806% faster than forkrun (1.0180x)   forkrun is 245.1% faster than parallel (3.4515x)
md5sum          1.4668794246    1.1723651055    1.1365918910    5.3246280195    xargs is 29.05% faster than forkrun (1.2905x)   forkrun is 262.9% faster than parallel (3.6299x)
sum -s          0.4980720323    0.3922736551    0.3521903143    4.9202543987    xargs is 11.38% faster than forkrun (1.1138x)   forkrun is 1154.% faster than parallel (12.542x)
sum -r          1.4861125105    1.2016379660    1.1555746630    5.3789883243    xargs is 3.986% faster than forkrun (1.0398x)   forkrun is 347.6% faster than parallel (4.4763x)
cksum           0.4427048144    0.3781248726    0.3373868298    4.9451578096    xargs is 12.07% faster than forkrun (1.1207x)   forkrun is 1207.% faster than parallel (13.078x)
b2sum           1.4134935179    1.3489518396    1.3045277342    5.4539864911    xargs is 3.405% faster than forkrun (1.0340x)   forkrun is 304.3% faster than parallel (4.0431x)
cksum -a sm3    3.5246299047    4.004003121     3.9460530153    5.9123989889    forkrun is 11.95% faster than xargs (1.1195x)   forkrun is 67.74% faster than parallel (1.6774x)

OVERALL         17.288055977    17.102648225    16.575140767    59.061267357    xargs is 3.182% faster than forkrun (1.0318x)   forkrun is 245.3% faster than parallel (3.4533x)




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         2.6497735473    3.1213456798    2.9833969183    12.486515358    forkrun is 12.59% faster than xargs (1.1259x)   forkrun is 371.2% faster than parallel (4.7122x)
sha256sum       5.4643695951    6.1982650898    5.9606813089    12.700176593    forkrun is 9.082% faster than xargs (1.0908x)   forkrun is 132.4% faster than parallel (2.3241x)
sha512sum       3.6959487322    4.4118286994    4.2385404680    12.593050225    forkrun is 14.68% faster than xargs (1.1468x)   forkrun is 240.7% faster than parallel (3.4072x)
sha224sum       5.2574896882    6.1934049415    5.9074818364    12.767211230    forkrun is 12.36% faster than xargs (1.1236x)   forkrun is 142.8% faster than parallel (2.4283x)
sha384sum       3.7434766256    4.3843723871    4.2503598377    12.642655356    forkrun is 13.54% faster than xargs (1.1354x)   forkrun is 237.7% faster than parallel (3.3772x)
md5sum          3.3010062543    3.5892329738    3.5287642209    12.623138410    forkrun is 6.899% faster than xargs (1.0689x)   forkrun is 282.4% faster than parallel (3.8240x)
sum -s          0.9469379107    0.8801419148    0.8354571413    11.549625763    xargs is 5.348% faster than forkrun (1.0534x)   forkrun is 1212.% faster than parallel (13.122x)
sum -r          3.4662771444    3.6659014289    3.6111428259    12.640306087    xargs is 1.516% faster than forkrun (1.0151x)   forkrun is 244.8% faster than parallel (3.4480x)
cksum           0.8296444603    0.7918990211    0.7384492966    11.539809791    xargs is 7.238% faster than forkrun (1.0723x)   forkrun is 1357.% faster than parallel (14.572x)
b2sum           3.3645041315    3.7847914805    3.6533223304    12.777252783    xargs is 3.598% faster than forkrun (1.0359x)   forkrun is 237.5% faster than parallel (3.3759x)
cksum -a sm3    10.088311143    11.291428700    10.895411649    14.681539787    forkrun is 8.000% faster than xargs (1.0800x)   forkrun is 45.53% faster than parallel (1.4553x)

OVERALL         42.807739233    48.312612317    46.603007834    139.00128138    forkrun is 8.865% faster than xargs (1.0886x)   forkrun is 224.7% faster than parallel (3.2471x)


-------------------------------- 1024 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      73.1 ms ±   0.3 ms    [User: 90.7 ms, System: 42.8 ms]
  Range (min … max):    72.5 ms …  73.8 ms    39 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      72.7 ms ±   0.3 ms    [User: 93.1 ms, System: 46.8 ms]
  Range (min … max):    72.1 ms …  73.9 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      79.2 ms ±   0.3 ms    [User: 65.3 ms, System: 17.2 ms]
  Range (min … max):    78.7 ms …  80.2 ms    36 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     198.3 ms ±   1.2 ms    [User: 215.8 ms, System: 143.4 ms]
  Range (min … max):   196.6 ms … 201.4 ms    14 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.09 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    2.73 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     118.2 ms ±   0.8 ms    [User: 158.9 ms, System: 42.9 ms]
  Range (min … max):   116.9 ms … 120.5 ms    24 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     116.8 ms ±   0.4 ms    [User: 159.9 ms, System: 47.8 ms]
  Range (min … max):   116.1 ms … 117.4 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     146.3 ms ±   0.6 ms    [User: 131.3 ms, System: 18.1 ms]
  Range (min … max):   145.4 ms … 147.9 ms    19 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     262.6 ms ±   0.5 ms    [User: 277.5 ms, System: 150.3 ms]
  Range (min … max):   261.6 ms … 263.0 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.25 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    2.25 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      91.5 ms ±   0.9 ms    [User: 118.3 ms, System: 44.5 ms]
  Range (min … max):    90.9 ms …  95.0 ms    31 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      90.9 ms ±   0.5 ms    [User: 121.9 ms, System: 47.5 ms]
  Range (min … max):    89.9 ms …  92.1 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     107.6 ms ±   0.4 ms    [User: 92.2 ms, System: 18.6 ms]
  Range (min … max):   107.0 ms … 108.7 ms    26 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     225.3 ms ±   0.6 ms    [User: 240.5 ms, System: 148.2 ms]
  Range (min … max):   224.3 ms … 226.6 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.18 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    2.48 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     118.0 ms ±   0.6 ms    [User: 160.4 ms, System: 40.9 ms]
  Range (min … max):   117.2 ms … 119.5 ms    24 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     117.3 ms ±   1.0 ms    [User: 161.3 ms, System: 47.1 ms]
  Range (min … max):   115.9 ms … 119.7 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     146.0 ms ±   1.4 ms    [User: 132.4 ms, System: 16.8 ms]
  Range (min … max):   144.9 ms … 151.4 ms    20 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     263.3 ms ±   0.9 ms    [User: 285.1 ms, System: 143.8 ms]
  Range (min … max):   262.3 ms … 265.6 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.25 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    2.25 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      91.4 ms ±   0.8 ms    [User: 119.7 ms, System: 42.0 ms]
  Range (min … max):    90.4 ms …  95.2 ms    31 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      90.7 ms ±   0.6 ms    [User: 122.1 ms, System: 46.4 ms]
  Range (min … max):    89.8 ms …  93.3 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     106.9 ms ±   0.5 ms    [User: 93.6 ms, System: 16.5 ms]
  Range (min … max):   106.1 ms … 108.0 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     225.6 ms ±   1.9 ms    [User: 240.7 ms, System: 148.3 ms]
  Range (min … max):   224.2 ms … 230.2 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.18 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    2.49 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      89.1 ms ±   0.3 ms    [User: 115.1 ms, System: 42.2 ms]
  Range (min … max):    88.5 ms …  90.2 ms    32 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      88.6 ms ±   0.6 ms    [User: 117.6 ms, System: 46.2 ms]
  Range (min … max):    87.8 ms …  90.8 ms    32 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     102.5 ms ±   0.9 ms    [User: 88.1 ms, System: 17.6 ms]
  Range (min … max):   101.6 ms … 106.4 ms    28 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     220.9 ms ±   0.6 ms    [User: 237.0 ms, System: 146.6 ms]
  Range (min … max):   219.6 ms … 221.8 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.16 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    2.49 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      38.5 ms ±   0.2 ms    [User: 40.2 ms, System: 39.9 ms]
  Range (min … max):    38.2 ms …  39.7 ms    71 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      37.7 ms ±   0.3 ms    [User: 41.5 ms, System: 42.2 ms]
  Range (min … max):    37.1 ms …  39.0 ms    72 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      29.5 ms ±   0.3 ms    [User: 15.3 ms, System: 17.6 ms]
  Range (min … max):    28.8 ms …  30.4 ms    91 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     174.4 ms ±   0.9 ms    [User: 159.1 ms, System: 139.3 ms]
  Range (min … max):   172.7 ms … 176.1 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.28 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.30 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    5.90 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      90.4 ms ±   0.4 ms    [User: 116.4 ms, System: 39.9 ms]
  Range (min … max):    89.1 ms …  91.0 ms    32 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      89.1 ms ±   0.5 ms    [User: 117.9 ms, System: 43.6 ms]
  Range (min … max):    88.5 ms …  90.8 ms    32 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     103.7 ms ±   0.4 ms    [User: 89.3 ms, System: 17.6 ms]
  Range (min … max):   102.8 ms … 104.5 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     222.3 ms ±   0.6 ms    [User: 237.2 ms, System: 137.0 ms]
  Range (min … max):   221.4 ms … 223.5 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.16 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    2.49 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
 
  Time (mean ± σ):      35.9 ms ±   0.4 ms    [User: 36.6 ms, System: 41.1 ms]
  Range (min … max):    35.5 ms …  38.5 ms    76 runs
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      35.8 ms ±   0.2 ms    [User: 38.7 ms, System: 45.9 ms]
  Range (min … max):    35.5 ms …  36.8 ms    76 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      25.3 ms ±   0.3 ms    [User: 11.4 ms, System: 17.3 ms]
  Range (min … max):    24.5 ms …  26.5 ms    103 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     175.0 ms ±   1.2 ms    [User: 155.6 ms, System: 149.9 ms]
  Range (min … max):   173.6 ms … 177.9 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.42 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.42 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    6.92 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      83.8 ms ±   0.4 ms    [User: 109.0 ms, System: 39.9 ms]
  Range (min … max):    83.0 ms …  84.5 ms    34 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      82.5 ms ±   0.5 ms    [User: 110.5 ms, System: 43.1 ms]
  Range (min … max):    81.2 ms …  83.4 ms    34 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):      95.6 ms ±   0.4 ms    [User: 81.7 ms, System: 17.1 ms]
  Range (min … max):    95.1 ms …  96.9 ms    30 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     214.2 ms ±   0.7 ms    [User: 226.8 ms, System: 139.3 ms]
  Range (min … max):   212.9 ms … 215.4 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.02 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.16 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    2.60 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     189.4 ms ±   1.6 ms    [User: 263.9 ms, System: 45.1 ms]
  Range (min … max):   188.5 ms … 195.0 ms    15 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     187.3 ms ±   1.0 ms    [User: 269.4 ms, System: 47.9 ms]
  Range (min … max):   186.4 ms … 190.2 ms    15 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     252.5 ms ±   3.5 ms    [User: 237.3 ms, System: 18.2 ms]
  Range (min … max):   250.6 ms … 263.1 ms    11 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
  Time (mean ± σ):     364.4 ms ±   0.6 ms    [User: 390.7 ms, System: 145.2 ms]
  Range (min … max):   363.8 ms … 365.5 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.35 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l
    1.95 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | wc -l

-------------------------------- 4096 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      66.9 ms ±   0.6 ms    [User: 123.7 ms, System: 66.9 ms]
  Range (min … max):    65.5 ms …  68.6 ms    42 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      63.6 ms ±   1.3 ms    [User: 126.0 ms, System: 69.1 ms]
  Range (min … max):    62.4 ms …  66.4 ms    43 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      59.7 ms ±   0.4 ms    [User: 92.0 ms, System: 41.9 ms]
  Range (min … max):    59.0 ms …  61.1 ms    47 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     223.5 ms ±   1.3 ms    [User: 286.0 ms, System: 174.2 ms]
  Range (min … max):   222.1 ms … 226.4 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.07 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.12 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    3.75 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      97.2 ms ±   1.7 ms    [User: 208.7 ms, System: 67.6 ms]
  Range (min … max):    94.2 ms … 100.4 ms    30 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
 
  Warning  Time (mean ± σ):      92.0 ms ±   2.3 ms    [User: 209.2 ms, System: 70.7 ms]
  Range (min … max):    90.4 ms … 101.1 ms    31 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      98.4 ms ±   0.5 ms    [User: 174.9 ms, System: 42.0 ms]
  Range (min … max):    97.6 ms …  99.5 ms    29 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     229.4 ms ±   0.7 ms    [User: 373.9 ms, System: 170.9 ms]
  Range (min … max):   228.4 ms … 230.6 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.07 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    2.49 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
 
  Warning  Time (mean ± σ):      81.0 ms ±   0.9 ms    [User: 166.1 ms, System: 67.8 ms]
  Range (min … max):    78.8 ms …  84.3 ms    35 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      76.4 ms ±   2.0 ms    [User: 168.6 ms, System: 70.0 ms]
  Range (min … max):    72.0 ms …  80.1 ms    37 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      78.5 ms ±   0.8 ms    [User: 135.1 ms, System: 40.8 ms]
  Range (min … max):    77.8 ms …  83.0 ms    36 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     223.2 ms ±   2.1 ms    [User: 330.4 ms, System: 172.4 ms]
  Range (min … max):   219.7 ms … 227.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.03 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    2.92 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      96.8 ms ±   1.2 ms    [User: 206.2 ms, System: 69.0 ms]
  Range (min … max):    93.9 ms … 100.5 ms    30 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      91.8 ms ±   2.2 ms    [User: 209.4 ms, System: 71.7 ms]
  Range (min … max):    86.7 ms …  95.7 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      98.1 ms ±   0.4 ms    [User: 173.3 ms, System: 43.1 ms]
  Range (min … max):    97.4 ms …  99.6 ms    29 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     229.7 ms ±   1.0 ms    [User: 371.2 ms, System: 175.2 ms]
  Range (min … max):   227.8 ms … 231.2 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.05 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.07 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    2.50 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      80.3 ms ±   0.7 ms    [User: 162.1 ms, System: 69.5 ms]
  Range (min … max):    79.4 ms …  82.5 ms    35 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      76.0 ms ±   1.8 ms    [User: 165.5 ms, System: 70.6 ms]
  Range (min … max):    71.4 ms …  79.1 ms    38 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      76.9 ms ±   0.2 ms    [User: 131.0 ms, System: 41.1 ms]
  Range (min … max):    76.4 ms …  77.4 ms    37 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     223.6 ms ±   1.4 ms    [User: 329.6 ms, System: 170.1 ms]
  Range (min … max):   221.2 ms … 226.0 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    2.94 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      77.3 ms ±   1.1 ms    [User: 150.9 ms, System: 68.5 ms]
  Range (min … max):    75.3 ms …  79.5 ms    37 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      73.8 ms ±   1.6 ms    [User: 154.0 ms, System: 69.2 ms]
  Range (min … max):    70.5 ms …  77.0 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      72.6 ms ±   0.3 ms    [User: 120.6 ms, System: 41.2 ms]
  Range (min … max):    72.1 ms …  74.0 ms    39 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     223.5 ms ±   1.2 ms    [User: 318.5 ms, System: 169.7 ms]
  Range (min … max):   220.9 ms … 225.6 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    3.08 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
 
    Time (mean ± σ):      44.8 ms ±   0.4 ms    [User: 60.9 ms, System: 64.1 ms]
  Range (min … max):    42.0 ms …  45.3 ms    62 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      42.4 ms ±   0.7 ms    [User: 63.0 ms, System: 66.3 ms]
  Range (min … max):    41.7 ms …  45.7 ms    65 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      31.4 ms ±   0.2 ms    [User: 32.6 ms, System: 39.5 ms]
  Range (min … max):    31.0 ms …  32.2 ms    85 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     224.3 ms ±   1.8 ms    [User: 231.6 ms, System: 159.7 ms]
  Range (min … max):   221.7 ms … 226.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.35 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.43 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    7.15 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      78.0 ms ±   0.5 ms    [User: 150.9 ms, System: 65.9 ms]
  Range (min … max):    77.0 ms …  80.4 ms    36 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      74.2 ms ±   1.4 ms    [User: 154.0 ms, System: 66.8 ms]
  Range (min … max):    72.8 ms …  76.6 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      73.0 ms ±   0.4 ms    [User: 119.2 ms, System: 42.6 ms]
  Range (min … max):    72.4 ms …  74.4 ms    38 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     224.2 ms ±   1.9 ms    [User: 317.2 ms, System: 162.6 ms]
  Range (min … max):   221.3 ms … 228.2 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.07 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    3.07 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      42.5 ms ±   0.4 ms    [User: 53.7 ms, System: 65.7 ms]
  Range (min … max):    41.9 ms …  43.9 ms    64 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      40.3 ms ±   0.6 ms    [User: 55.2 ms, System: 68.0 ms]
  Range (min … max):    39.7 ms …  42.0 ms    68 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      27.8 ms ±   0.2 ms    [User: 24.3 ms, System: 39.5 ms]
  Range (min … max):    27.4 ms …  28.5 ms    95 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     224.8 ms ±   0.8 ms    [User: 227.6 ms, System: 166.8 ms]
  Range (min … max):   223.2 ms … 225.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.45 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.53 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    8.08 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      75.8 ms ±   0.8 ms    [User: 149.9 ms, System: 65.3 ms]
  Range (min … max):    73.5 ms …  78.1 ms    37 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      72.6 ms ±   2.6 ms    [User: 152.6 ms, System: 67.8 ms]
  Range (min … max):    70.2 ms …  85.2 ms    40 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):      71.3 ms ±   0.4 ms    [User: 118.3 ms, System: 41.5 ms]
  Range (min … max):    70.5 ms …  73.0 ms    40 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     223.1 ms ±   0.8 ms    [User: 312.5 ms, System: 163.5 ms]
  Range (min … max):   222.1 ms … 224.2 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.02 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.06 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    3.13 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     143.5 ms ±   1.6 ms    [User: 339.6 ms, System: 68.3 ms]
  Range (min … max):   142.5 ms … 148.1 ms    20 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     135.3 ms ±   2.6 ms    [User: 339.7 ms, System: 72.6 ms]
  Range (min … max):   129.7 ms … 141.3 ms    21 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     158.9 ms ±   0.4 ms    [User: 300.7 ms, System: 45.5 ms]
  Range (min … max):   158.2 ms … 159.8 ms    18 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
  Time (mean ± σ):     268.6 ms ±   0.9 ms    [User: 501.3 ms, System: 173.8 ms]
  Range (min … max):   267.6 ms … 270.2 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l ran
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.17 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l
    1.99 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | wc -l

-------------------------------- 16384 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning  Time (mean ± σ):     191.0 ms ±   6.5 ms    [User: 858.6 ms, System: 248.6 ms]
  Range (min … max):   186.5 ms … 204.7 ms    15 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     190.9 ms ±  10.3 ms    [User: 942.6 ms, System: 272.7 ms]
  Range (min … max):   182.3 ms … 211.1 ms    16 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     239.5 ms ±   0.7 ms    [User: 757.5 ms, System: 196.4 ms]
  Range (min … max):   238.7 ms … 240.9 ms    12 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     471.4 ms ±   1.6 ms    [User: 1196.7 ms, System: 375.6 ms]
  Range (min … max):   469.5 ms … 474.7 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.00 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.25 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    2.47 ± 0.13 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning  Time (mean ± σ):     337.1 ms ±  11.6 ms    [User: 1675.4 ms, System: 250.3 ms]
  Range (min … max):   331.9 ms … 369.3 ms    10 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning  Time (mean ± σ):     344.9 ms ±  16.8 ms    [User: 1837.5 ms, System: 277.0 ms]
  Range (min … max):   333.1 ms … 376.8 ms    10 runs
: The first benchmarking run for this command was significantly slower than the rest (366.7 ms). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     468.1 ms ±   0.8 ms    [User: 1554.1 ms, System: 209.8 ms]
  Range (min … max):   466.8 ms … 469.2 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     552.2 ms ±   1.7 ms    [User: 2023.9 ms, System: 380.3 ms]
  Range (min … max):   549.3 ms … 554.4 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.02 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.39 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.64 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
    Time (mean ± σ):     250.9 ms ±   8.4 ms    [User: 1218.0 ms, System: 258.3 ms]
  Range (min … max):   247.0 ms … 276.0 ms    11 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     260.5 ms ±  15.6 ms    [User: 1380.7 ms, System: 267.8 ms]
  Range (min … max):   243.6 ms … 279.8 ms    11 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     332.9 ms ±   0.6 ms    [User: 1108.6 ms, System: 200.1 ms]
  Range (min … max):   332.1 ms … 334.1 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     503.0 ms ±   2.7 ms    [User: 1562.4 ms, System: 375.8 ms]
  Range (min … max):   498.9 ms … 508.4 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.04 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.33 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    2.00 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning  Time (mean ± σ):     335.1 ms ±   7.2 ms    [User: 1675.8 ms, System: 255.9 ms]
  Range (min … max):   331.4 ms … 354.8 ms    10 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     352.5 ms ±  22.1 ms    [User: 1841.6 ms, System: 266.1 ms]
  Range (min … max):   332.5 ms … 386.2 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     467.5 ms ±   0.6 ms    [User: 1557.7 ms, System: 202.4 ms]
  Range (min … max):   467.0 ms … 469.2 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     550.9 ms ±   1.4 ms    [User: 2020.6 ms, System: 377.8 ms]
  Range (min … max):   548.3 ms … 552.2 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.05 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.40 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.64 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     247.0 ms ±   0.9 ms    [User: 1203.1 ms, System: 253.8 ms]
  Range (min … max):   245.4 ms … 248.3 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     259.1 ms ±  17.9 ms    [User: 1343.1 ms, System: 280.3 ms]
  Range (min … max):   242.7 ms … 300.7 ms    11 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     331.8 ms ±   0.9 ms    [User: 1095.7 ms, System: 199.6 ms]
  Range (min … max):   330.7 ms … 333.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     502.9 ms ±   3.4 ms    [User: 1541.0 ms, System: 386.2 ms]
  Range (min … max):   496.5 ms … 507.8 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.05 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.34 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    2.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     237.8 ms ±   1.0 ms    [User: 1115.8 ms, System: 256.3 ms]
  Range (min … max):   236.5 ms … 240.6 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     239.4 ms ±   4.5 ms    [User: 1158.9 ms, System: 277.3 ms]
  Range (min … max):   234.2 ms … 244.4 ms    12 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     320.3 ms ±   3.2 ms    [User: 1035.2 ms, System: 200.2 ms]
  Range (min … max):   318.6 ms … 329.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     496.7 ms ±   2.2 ms    [User: 1479.9 ms, System: 376.8 ms]
  Range (min … max):   494.3 ms … 501.9 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.35 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    2.09 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):      82.1 ms ±   1.0 ms    [User: 236.4 ms, System: 243.1 ms]
  Range (min … max):    79.8 ms …  84.6 ms    34 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):      77.2 ms ±   2.9 ms    [User: 261.9 ms, System: 269.6 ms]
  Range (min … max):    73.3 ms …  83.4 ms    37 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):      69.4 ms ±   0.4 ms    [User: 162.9 ms, System: 188.9 ms]
  Range (min … max):    68.8 ms …  70.6 ms    41 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     450.1 ms ±   2.3 ms    [User: 609.9 ms, System: 351.5 ms]
  Range (min … max):   445.9 ms … 453.2 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.11 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.18 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    6.49 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning  Time (mean ± σ):     242.4 ms ±   4.7 ms    [User: 1140.3 ms, System: 241.4 ms]
  Range (min … max):   239.0 ms … 254.0 ms    12 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     244.4 ms ±   6.1 ms    [User: 1181.4 ms, System: 267.0 ms]
  Range (min … max):   238.5 ms … 254.7 ms    12 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     326.0 ms ±   4.1 ms    [User: 1048.5 ms, System: 200.2 ms]
  Range (min … max):   323.8 ms … 337.5 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     498.9 ms ±   1.8 ms    [User: 1494.1 ms, System: 361.8 ms]
  Range (min … max):   495.8 ms … 501.4 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.01 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.35 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    2.06 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):      73.5 ms ±   1.1 ms    [User: 181.0 ms, System: 244.3 ms]
  Range (min … max):    70.9 ms …  77.9 ms    38 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):      68.7 ms ±   2.7 ms    [User: 197.7 ms, System: 271.2 ms]
  Range (min … max):    65.7 ms …  77.7 ms    42 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):      55.7 ms ±   0.4 ms    [User: 107.5 ms, System: 187.1 ms]
  Range (min … max):    55.0 ms …  56.8 ms    50 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     449.7 ms ±   1.8 ms    [User: 563.2 ms, System: 357.2 ms]
  Range (min … max):   446.9 ms … 452.0 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.23 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.32 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    8.07 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning  Time (mean ± σ):     225.0 ms ±   4.8 ms    [User: 1067.7 ms, System: 248.7 ms]
  Range (min … max):   222.5 ms … 240.9 ms    13 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     230.0 ms ±  13.2 ms    [User: 1194.1 ms, System: 271.4 ms]
  Range (min … max):   217.2 ms … 252.4 ms    13 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     293.3 ms ±   0.8 ms    [User: 969.6 ms, System: 194.2 ms]
  Range (min … max):   291.6 ms … 294.2 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     487.6 ms ±   1.4 ms    [User: 1412.4 ms, System: 363.3 ms]
  Range (min … max):   486.7 ms … 491.0 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.02 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.30 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    2.17 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     573.1 ms ±   0.9 ms    [User: 2969.3 ms, System: 257.1 ms]
  Range (min … max):   571.7 ms … 574.3 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
  Time (mean ± σ):     573.7 ms ±   1.8 ms    [User: 3244.2 ms, System: 279.6 ms]
  Range (min … max):   571.6 ms … 578.1 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning: The first benchmarking run for this command was significantly slower than the rest (865.2 ms). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
  Time (mean ± σ):     836.0 ms ±  10.3 ms    [User: 2833.1 ms, System: 214.1 ms]
  Range (min … max):   832.1 ms … 865.2 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     771.5 ms ±   6.0 ms    [User: 3303.0 ms, System: 388.4 ms]
  Range (min … max):   769.2 ms … 788.5 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l ran
    1.00 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.35 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l
    1.46 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | wc -l

-------------------------------- 65536 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     331.5 ms ±   9.8 ms    [User: 2796.5 ms, System: 842.9 ms]
  Range (min … max):   323.7 ms … 356.0 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     309.9 ms ±  14.5 ms    [User: 4192.5 ms, System: 1005.2 ms]
  Range (min … max):   286.0 ms … 328.3 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     294.9 ms ±   7.7 ms    [User: 3762.4 ms, System: 838.6 ms]
  Range (min … max):   281.0 ms … 307.9 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.376 s ±  0.013 s    [User: 3.828 s, System: 1.046 s]
  Range (min … max):    1.364 s …  1.410 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.05 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.12 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    4.67 ± 0.13 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     570.5 ms ±   9.1 ms    [User: 5427.0 ms, System: 861.7 ms]
  Range (min … max):   560.1 ms … 585.7 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     546.4 ms ±  21.1 ms    [User: 8485.7 ms, System: 999.0 ms]
  Range (min … max):   506.8 ms … 582.8 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     552.1 ms ±  16.1 ms    [User: 7885.9 ms, System: 843.4 ms]
  Range (min … max):   533.7 ms … 572.9 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.435 s ±  0.011 s    [User: 6.426 s, System: 1.036 s]
  Range (min … max):    1.422 s …  1.462 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.01 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.04 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    2.63 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     437.4 ms ±  11.9 ms    [User: 3987.0 ms, System: 871.3 ms]
  Range (min … max):   427.3 ms … 463.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     417.4 ms ±  19.6 ms    [User: 6324.4 ms, System: 989.7 ms]
  Range (min … max):   393.1 ms … 451.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     412.5 ms ±  13.3 ms    [User: 5715.3 ms, System: 854.9 ms]
  Range (min … max):   397.1 ms … 438.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.377 s ±  0.009 s    [User: 4.975 s, System: 1.043 s]
  Range (min … max):    1.363 s …  1.392 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.01 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.06 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    3.34 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     565.2 ms ±  10.4 ms    [User: 5364.6 ms, System: 862.4 ms]
  Range (min … max):   555.2 ms … 589.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     542.2 ms ±  24.2 ms    [User: 8401.0 ms, System: 989.8 ms]
  Range (min … max):   511.4 ms … 575.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     563.8 ms ±  19.9 ms    [User: 7874.1 ms, System: 836.9 ms]
  Range (min … max):   522.0 ms … 586.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.433 s ±  0.011 s    [User: 6.388 s, System: 1.052 s]
  Range (min … max):    1.414 s …  1.452 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.04 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.04 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    2.64 ± 0.12 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     432.1 ms ±  12.3 ms    [User: 3950.1 ms, System: 846.2 ms]
  Range (min … max):   423.3 ms … 464.4 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     401.9 ms ±  15.5 ms    [User: 6144.9 ms, System: 996.0 ms]
  Range (min … max):   377.8 ms … 429.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     424.2 ms ±  20.4 ms    [User: 5614.2 ms, System: 853.9 ms]
  Range (min … max):   395.7 ms … 457.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.382 s ±  0.013 s    [User: 4.917 s, System: 1.048 s]
  Range (min … max):    1.364 s …  1.410 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.06 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.08 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    3.44 ± 0.14 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     401.9 ms ±   2.3 ms    [User: 3590.3 ms, System: 847.8 ms]
  Range (min … max):   398.0 ms … 404.5 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     325.1 ms ±   8.6 ms    [User: 4177.3 ms, System: 1006.6 ms]
  Range (min … max):   313.9 ms … 342.3 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     331.1 ms ±   7.4 ms    [User: 3875.3 ms, System: 843.6 ms]
  Range (min … max):   319.2 ms … 345.2 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.379 s ±  0.012 s    [User: 4.714 s, System: 1.032 s]
  Range (min … max):    1.366 s …  1.406 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.02 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.24 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    4.24 ± 0.12 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     151.4 ms ±   2.1 ms    [User: 823.3 ms, System: 803.1 ms]
  Range (min … max):   148.1 ms … 154.6 ms    19 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     131.0 ms ±   3.1 ms    [User: 1036.8 ms, System: 993.4 ms]
  Range (min … max):   126.5 ms … 138.0 ms    21 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     114.4 ms ±   7.3 ms    [User: 704.1 ms, System: 779.7 ms]
  Range (min … max):   105.8 ms … 126.6 ms    23 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.339 s ±  0.009 s    [User: 1.989 s, System: 0.988 s]
  Range (min … max):    1.329 s …  1.354 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.15 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.32 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
   11.71 ± 0.76 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     406.0 ms ±   2.3 ms    [User: 3651.6 ms, System: 827.1 ms]
  Range (min … max):   401.6 ms … 410.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     328.8 ms ±   8.9 ms    [User: 4257.5 ms, System: 955.5 ms]
  Range (min … max):   317.7 ms … 345.3 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     334.3 ms ±   8.9 ms    [User: 3936.7 ms, System: 818.1 ms]
  Range (min … max):   321.8 ms … 346.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.366 s ±  0.008 s    [User: 4.735 s, System: 1.013 s]
  Range (min … max):    1.358 s …  1.382 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.02 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.23 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    4.15 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     137.6 ms ±   1.6 ms    [User: 631.0 ms, System: 811.5 ms]
  Range (min … max):   135.5 ms … 141.7 ms    21 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     122.2 ms ±   3.1 ms    [User: 755.2 ms, System: 973.8 ms]
  Range (min … max):   117.2 ms … 128.7 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
 
  Warning:   Time (mean ± σ):     102.6 ms ±   2.5 ms    [User: 432.9 ms, System: 727.1 ms]
  Range (min … max):    97.9 ms … 111.6 ms    28 runs
Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.340 s ±  0.023 s    [User: 1.815 s, System: 1.000 s]
  Range (min … max):    1.325 s …  1.384 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.19 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.34 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
   13.06 ± 0.39 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     387.6 ms ±   5.4 ms    [User: 3533.0 ms, System: 827.6 ms]
  Range (min … max):   381.2 ms … 398.2 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     371.0 ms ±  14.5 ms    [User: 5325.0 ms, System: 987.9 ms]
  Range (min … max):   353.1 ms … 385.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     367.8 ms ±  14.1 ms    [User: 4823.6 ms, System: 839.0 ms]
  Range (min … max):   352.1 ms … 385.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.374 s ±  0.006 s    [User: 4.517 s, System: 1.013 s]
  Range (min … max):    1.363 s …  1.381 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.01 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.05 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    3.73 ± 0.14 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     935.4 ms ±   7.1 ms    [User: 9450.3 ms, System: 884.9 ms]
  Range (min … max):   927.2 ms … 948.2 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     924.7 ms ±  26.8 ms    [User: 15601.8 ms, System: 1088.9 ms]
  Range (min … max):   890.3 ms … 956.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):     968.2 ms ±  16.6 ms    [User: 14980.2 ms, System: 942.2 ms]
  Range (min … max):   936.0 ms … 995.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
  Time (mean ± σ):      1.560 s ±  0.007 s    [User: 10.468 s, System: 1.068 s]
  Range (min … max):    1.551 s …  1.572 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l ran
    1.01 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.05 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l
    1.69 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | wc -l

-------------------------------- 262144 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.206 s ±  0.004 s    [User: 12.297 s, System: 3.411 s]
  Range (min … max):    1.197 s …  1.213 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.133 s ±  0.013 s    [User: 19.590 s, System: 4.025 s]
  Range (min … max):    1.114 s …  1.162 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.088 s ±  0.039 s    [User: 18.513 s, System: 3.618 s]
  Range (min … max):    1.049 s …  1.174 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      5.202 s ±  0.035 s    [User: 16.055 s, System: 3.889 s]
  Range (min … max):    5.136 s …  5.238 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.04 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.11 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    4.78 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      2.123 s ±  0.011 s    [User: 23.937 s, System: 3.485 s]
  Range (min … max):    2.099 s …  2.143 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      2.186 s ±  0.016 s    [User: 40.276 s, System: 4.090 s]
  Range (min … max):    2.168 s …  2.212 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      2.157 s ±  0.025 s    [User: 39.091 s, System: 3.676 s]
  Range (min … max):    2.125 s …  2.200 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      5.538 s ±  0.041 s    [User: 27.695 s, System: 4.011 s]
  Range (min … max):    5.479 s …  5.616 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.02 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    2.61 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.619 s ±  0.006 s    [User: 17.551 s, System: 3.503 s]
  Range (min … max):    1.610 s …  1.629 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.605 s ±  0.027 s    [User: 29.362 s, System: 4.026 s]
  Range (min … max):    1.572 s …  1.656 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.561 s ±  0.021 s    [User: 28.192 s, System: 3.596 s]
  Range (min … max):    1.527 s …  1.590 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      5.370 s ±  0.052 s    [User: 21.191 s, System: 4.000 s]
  Range (min … max):    5.303 s …  5.469 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.04 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    3.44 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      2.116 s ±  0.008 s    [User: 23.892 s, System: 3.471 s]
  Range (min … max):    2.106 s …  2.127 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      2.191 s ±  0.015 s    [User: 40.078 s, System: 4.097 s]
  Range (min … max):    2.169 s …  2.213 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      2.135 s ±  0.032 s    [User: 38.974 s, System: 3.650 s]
  Range (min … max):    2.078 s …  2.169 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      5.559 s ±  0.064 s    [User: 27.678 s, System: 4.013 s]
  Range (min … max):    5.500 s …  5.728 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.04 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    2.63 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.601 s ±  0.007 s    [User: 17.324 s, System: 3.460 s]
  Range (min … max):    1.590 s …  1.611 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.588 s ±  0.021 s    [User: 28.779 s, System: 4.028 s]
  Range (min … max):    1.566 s …  1.629 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.549 s ±  0.017 s    [User: 27.753 s, System: 3.578 s]
  Range (min … max):    1.519 s …  1.576 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      5.342 s ±  0.033 s    [User: 20.961 s, System: 3.976 s]
  Range (min … max):    5.294 s …  5.408 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    3.45 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.491 s ±  0.002 s    [User: 15.831 s, System: 3.449 s]
  Range (min … max):    1.488 s …  1.496 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.190 s ±  0.015 s    [User: 18.914 s, System: 4.089 s]
  Range (min … max):    1.175 s …  1.227 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.154 s ±  0.011 s    [User: 17.901 s, System: 3.644 s]
  Range (min … max):    1.134 s …  1.172 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      5.318 s ±  0.038 s    [User: 20.004 s, System: 3.946 s]
  Range (min … max):    5.259 s …  5.365 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.29 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    4.61 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):     511.6 ms ±   2.0 ms    [User: 3461.2 ms, System: 3243.1 ms]
  Range (min … max):   508.0 ms … 514.2 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):     405.6 ms ±   4.3 ms    [User: 4446.9 ms, System: 4040.3 ms]
  Range (min … max):   401.9 ms … 413.3 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):     353.7 ms ±   7.0 ms    [User: 3276.9 ms, System: 3533.7 ms]
  Range (min … max):   343.1 ms … 363.5 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      4.919 s ±  0.024 s    [User: 7.721 s, System: 3.671 s]
  Range (min … max):    4.893 s …  4.953 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.15 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.45 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
   13.91 ± 0.28 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.509 s ±  0.004 s    [User: 16.190 s, System: 3.333 s]
  Range (min … max):    1.504 s …  1.518 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.208 s ±  0.010 s    [User: 19.128 s, System: 3.867 s]
  Range (min … max):    1.199 s …  1.230 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.167 s ±  0.010 s    [User: 18.110 s, System: 3.526 s]
  Range (min … max):    1.148 s …  1.178 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      5.297 s ±  0.049 s    [User: 20.207 s, System: 3.810 s]
  Range (min … max):    5.223 s …  5.408 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.29 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    4.54 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):     452.9 ms ±   3.5 ms    [User: 2599.7 ms, System: 3277.1 ms]
  Range (min … max):   444.3 ms … 455.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):     383.6 ms ±   2.1 ms    [User: 3117.2 ms, System: 3823.5 ms]
  Range (min … max):   379.9 ms … 386.0 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):     347.7 ms ±   5.8 ms    [User: 1854.9 ms, System: 3124.6 ms]
  Range (min … max):   337.6 ms … 357.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      4.920 s ±  0.061 s    [User: 6.959 s, System: 3.702 s]
  Range (min … max):    4.854 s …  5.051 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.10 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.30 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
   14.15 ± 0.29 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.451 s ±  0.005 s    [User: 15.530 s, System: 3.355 s]
  Range (min … max):    1.444 s …  1.463 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.366 s ±  0.017 s    [User: 24.428 s, System: 3.987 s]
  Range (min … max):    1.338 s …  1.397 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      1.330 s ±  0.015 s    [User: 23.401 s, System: 3.600 s]
  Range (min … max):    1.307 s …  1.353 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      5.336 s ±  0.063 s    [User: 19.094 s, System: 3.905 s]
  Range (min … max):    5.279 s …  5.469 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.09 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    4.01 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      3.571 s ±  0.010 s    [User: 42.156 s, System: 3.586 s]
  Range (min … max):    3.556 s …  3.586 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      3.992 s ±  0.025 s    [User: 76.387 s, System: 4.717 s]
  Range (min … max):    3.961 s …  4.035 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      3.956 s ±  0.057 s    [User: 74.937 s, System: 4.248 s]
  Range (min … max):    3.863 s …  4.014 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
  Time (mean ± σ):      5.941 s ±  0.053 s    [User: 46.095 s, System: 4.122 s]
  Range (min … max):    5.845 s …  6.014 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l ran
    1.11 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.12 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l
    1.66 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | wc -l

-------------------------------- 586011 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      2.884 s ±  0.126 s    [User: 24.736 s, System: 6.453 s]
  Range (min … max):    2.752 s …  3.154 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.148 s ±  0.026 s    [User: 40.203 s, System: 8.418 s]
  Range (min … max):    3.108 s …  3.194 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      2.994 s ±  0.030 s    [User: 35.603 s, System: 7.452 s]
  Range (min … max):    2.948 s …  3.044 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     12.490 s ±  0.225 s    [User: 35.579 s, System: 8.571 s]
  Range (min … max):   12.263 s … 12.971 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.04 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.09 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    4.33 ± 0.21 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      5.660 s ±  0.128 s    [User: 48.676 s, System: 6.472 s]
  Range (min … max):    5.448 s …  5.850 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      6.215 s ±  0.023 s    [User: 81.005 s, System: 8.474 s]
  Range (min … max):    6.174 s …  6.243 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      6.000 s ±  0.071 s    [User: 72.679 s, System: 7.384 s]
  Range (min … max):    5.944 s …  6.157 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     12.770 s ±  0.181 s    [User: 60.133 s, System: 8.704 s]
  Range (min … max):   12.548 s … 13.189 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.10 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    2.26 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.977 s ±  0.141 s    [User: 35.941 s, System: 6.310 s]
  Range (min … max):    3.853 s …  4.262 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      4.448 s ±  0.015 s    [User: 60.099 s, System: 8.350 s]
  Range (min … max):    4.431 s …  4.476 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      4.300 s ±  0.054 s    [User: 54.212 s, System: 7.426 s]
  Range (min … max):    4.258 s …  4.437 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     12.698 s ±  0.159 s    [User: 46.548 s, System: 8.710 s]
  Range (min … max):   12.494 s … 12.952 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.08 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.12 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    3.19 ± 0.12 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      5.652 s ±  0.282 s    [User: 48.000 s, System: 6.453 s]
  Range (min … max):    5.396 s …  6.384 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      6.217 s ±  0.034 s    [User: 80.936 s, System: 8.548 s]
  Range (min … max):    6.176 s …  6.270 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      5.999 s ±  0.052 s    [User: 72.285 s, System: 7.390 s]
  Range (min … max):    5.927 s …  6.100 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     12.649 s ±  0.149 s    [User: 59.915 s, System: 8.697 s]
  Range (min … max):   12.479 s … 12.960 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.06 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.10 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    2.24 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      4.037 s ±  0.206 s    [User: 35.369 s, System: 6.337 s]
  Range (min … max):    3.814 s …  4.479 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      4.430 s ±  0.028 s    [User: 58.770 s, System: 8.372 s]
  Range (min … max):    4.397 s …  4.470 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      4.293 s ±  0.059 s    [User: 53.143 s, System: 7.402 s]
  Range (min … max):    4.228 s …  4.418 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     12.706 s ±  0.197 s    [User: 46.018 s, System: 8.731 s]
  Range (min … max):   12.431 s … 13.031 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.06 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.10 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    3.15 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.564 s ±  0.018 s    [User: 29.335 s, System: 6.464 s]
  Range (min … max):    3.532 s …  3.590 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.594 s ±  0.017 s    [User: 39.781 s, System: 8.541 s]
  Range (min … max):    3.566 s …  3.624 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.555 s ±  0.030 s    [User: 36.891 s, System: 7.517 s]
  Range (min … max):    3.525 s …  3.624 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     12.521 s ±  0.119 s    [User: 43.960 s, System: 8.606 s]
  Range (min … max):   12.367 s … 12.739 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.00 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    3.52 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     993.8 ms ±  21.1 ms    [User: 6686.2 ms, System: 5902.7 ms]
  Range (min … max):   963.8 ms … 1031.9 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     891.9 ms ±  10.5 ms    [User: 9350.0 ms, System: 8071.9 ms]
  Range (min … max):   876.0 ms … 912.8 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     853.1 ms ±  14.6 ms    [User: 6766.4 ms, System: 7055.0 ms]
  Range (min … max):   836.6 ms … 886.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     11.615 s ±  0.164 s    [User: 17.425 s, System: 7.903 s]
  Range (min … max):   11.449 s … 11.885 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.05 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.16 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
   13.61 ± 0.30 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.691 s ±  0.051 s    [User: 29.172 s, System: 6.331 s]
  Range (min … max):    3.613 s …  3.779 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.683 s ±  0.018 s    [User: 40.420 s, System: 8.133 s]
  Range (min … max):    3.648 s …  3.710 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.632 s ±  0.037 s    [User: 37.319 s, System: 7.240 s]
  Range (min … max):    3.580 s …  3.708 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     12.649 s ±  0.163 s    [User: 44.488 s, System: 8.407 s]
  Range (min … max):   12.482 s … 12.937 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    3.48 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     859.4 ms ±  10.5 ms    [User: 4929.9 ms, System: 5912.2 ms]
  Range (min … max):   845.2 ms … 879.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     810.6 ms ±  11.3 ms    [User: 6623.4 ms, System: 7880.4 ms]
  Range (min … max):   794.5 ms … 828.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     762.4 ms ±   6.2 ms    [User: 4053.6 ms, System: 6522.7 ms]
  Range (min … max):   751.8 ms … 770.1 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     11.455 s ±  0.116 s    [User: 15.672 s, System: 7.897 s]
  Range (min … max):   11.319 s … 11.747 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.13 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
   15.02 ± 0.19 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.481 s ±  0.156 s    [User: 31.168 s, System: 6.243 s]
  Range (min … max):    3.354 s …  3.836 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.821 s ±  0.028 s    [User: 50.539 s, System: 8.236 s]
  Range (min … max):    3.786 s …  3.873 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):      3.688 s ±  0.030 s    [User: 45.903 s, System: 7.404 s]
  Range (min … max):    3.639 s …  3.748 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     12.620 s ±  0.161 s    [User: 42.120 s, System: 8.551 s]
  Range (min … max):   12.436 s … 13.009 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.06 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.10 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    3.63 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     10.289 s ±  0.702 s    [User: 87.043 s, System: 6.658 s]
  Range (min … max):    9.546 s … 11.687 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     11.368 s ±  0.171 s    [User: 150.868 s, System: 9.472 s]
  Range (min … max):   11.208 s … 11.706 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     10.931 s ±  0.150 s    [User: 135.246 s, System: 8.184 s]
  Range (min … max):   10.752 s … 11.191 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
  Time (mean ± σ):     14.675 s ±  0.102 s    [User: 100.003 s, System: 9.221 s]
  Range (min … max):   14.577 s … 14.863 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l ran
    1.06 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.10 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l
    1.43 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | wc -l

-----------------------------------------------------
-------------------- "min" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0725486833    0.0721279643    0.0787023983    0.1966461853    0.1168950752    0.1160656842    0.1453824622    0.2615791422    0.0908678645    0.0899348845    0.1069611765    0.2242981705    0.1171633078    0.1158544378    0.1449266658    0.2623048258    0.0904467872    0.0898056852    0.1061103872    0.2242266682        0.0885013810    0.0878013100    0.1016451660    0.2196271470    0.0381835429    0.0370684919    0.0288116109    0.1726988459    0.0891012564    0.0884724684    0.1028417314    0.2213769724    0.0355004892    0.0355297992    0.0245095742    0.1735595442    0.0829632314    0.0811919584    0.09511480340.2128599944    0.1884685752    0.1863756622    0.2505979902    0.3637860692
4096    0.0655354057    0.0623869397    0.0589833477    0.2220800677    0.0941923247    0.0904188187    0.0976309977    0.2284162747    0.0788058683    0.0719709343    0.0777706953    0.2196706963    0.0939131112    0.0867490932    0.0973769392    0.2277870852    0.0793689067    0.0713528077    0.0764297847    0.2212255837        0.0753008351    0.0705080471    0.0721168201    0.2209089151    0.0419728933    0.0416832233    0.0309651903    0.2217110453    0.0770221267    0.0727822457    0.0724460277    0.2212569437    0.0419062346    0.0396516696    0.0274236296    0.2231831836    0.0735043852    0.0701669242    0.07053327720.2221198232    0.1424993380    0.1296523370    0.1582246660    0.2675560610
16384   0.1865027709    0.1823233579    0.2386699379    0.4694689749    0.3319061016    0.3331384196    0.4668071546    0.5492595586    0.2470099794    0.2435884234    0.3320912314    0.4989222104    0.3313736018    0.3325304648    0.4669883328    0.5482646198    0.2454459488    0.2427408998    0.3306696038    0.4965437998        0.2365458206    0.2341854806    0.3185855646    0.4943002946    0.0797545320    0.0732729430    0.0688179880    0.4458669490    0.2389519391    0.2384714231    0.3237697691    0.4958018731    0.0709049758    0.0656558108    0.0550003078    0.4469034008    0.2224700100    0.2171943930    0.29157746700.4866586060    0.5717339409    0.5715873339    0.8321258329    0.7691841119
65536   0.3236538293    0.2860297533    0.2809719063    1.3640962593    0.5601401487    0.5067845297    0.5336504637    1.4215832837    0.4272829525    0.3930845715    0.3970596275    1.3629889475    0.5551704388    0.5113715258    0.5220342098    1.4135286178    0.4233344254    0.3777792634    0.3956724494    1.3643515014        0.3980151923    0.3138732743    0.3192208833    1.3662418893    0.1480729545    0.1264942395    0.1058360085    1.3292256545    0.4016365506    0.3177175156    0.3218118906    1.3582768406    0.1355415779    0.1172112539    0.0978655889    1.3253358999    0.3812430983    0.3530533493    0.35208088531.3632280293    0.9272030877    0.8902954157    0.9360233417    1.5513350137
262144  1.1972989309    1.1144478069    1.0487021229    5.1360421179    2.0993342185    2.1675521085    2.1251025005    5.4794397835    1.6099117668    1.5723567368    1.5265325818    5.3029367118    2.1061047361    2.1690898910    2.0777617581    5.5002072641    1.5897081504    1.5664894164    1.5190631294    5.2943175104        1.4876151848    1.1746217948    1.1338007218    5.2591520427    0.5079900327    0.4018727417    0.3430804057    4.8934199427    1.5036135810    1.1992368670    1.1480825270    5.2230858490    0.4442879152    0.3798512002    0.3376286262    4.8536968162    1.4435931225    1.3384271495    1.30667880355.2792287995    3.5559360101    3.9606130131    3.8625199121    5.8447022741
586011  2.7515225772    3.1084163992    2.9483681552    12.262536040    5.4479728051    6.1744964891    5.9437243291    12.548306437    3.8526343964    4.4307978124    4.2580871074    12.494237407    5.3963862035    6.1760485415    5.9273646425    12.479042124    3.8142219685    4.3965592645    4.2278637205    12.430855385        3.5319590783    3.5660117583    3.5248389763    12.366556395    0.9637868946    0.8759957286    0.8365586966    11.449425095    3.6125086189    3.6477325579    3.5798614289    12.481678892    0.8451757096    0.7944520166    0.7518305226    11.318609928    3.3539838393    3.7862615503    3.639286769312.436268339    9.5457362400    11.208392552    10.752424557    14.577445143

-----------------------------------------------------
-------------------- "mean" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0730518678    0.0726516056    0.0792227436    0.1982759592    0.1181867048    0.1167904776    0.1463040885    0.2626038960    0.0915359840    0.0908748963    0.1076036246    0.2252557624    0.1179767674    0.1172630170    0.1460100702    0.2632914574    0.0913766370    0.0906554735    0.1069279112    0.2256200863        0.0890722645    0.0885602411    0.1025294036    0.2208817104    0.0384651880    0.0377418936    0.0295401546    0.1744338733    0.0904119870    0.0890912982    0.1036866706    0.2222509364    0.0359033759    0.0358492843    0.0252940136    0.1749671145    0.0837604766    0.0824591534    0.09564879500.2141598351    0.189431657,    0.1872982812    0.2525056671    0.364440035,
4096    0.0668608090    0.0636300662    0.0596535882    0.2235040673    0.0971956319    0.0920190336    0.0983732376    0.2294493408    0.0809913311    0.0764260806    0.0785435763    0.2232483140    0.0967508951    0.0918358612    0.0980551429    0.2296537546    0.0802556491    0.0759840288    0.0769347817    0.2235948712        0.0773295460    0.0737700811    0.0726324909    0.2234840200    0.0447589359    0.0424078085    0.0313619292    0.2242520554    0.0779810405    0.0741920094    0.0729668465    0.2241976680    0.0424533731    0.0403091835    0.0278372356    0.2248445139    0.0757823090    0.0726048154    0.07130346960.2231194351    0.1435031647    0.1352685762    0.1589066921    0.2686105604
16384   0.1910319961    0.1909195783    0.2395306548    0.4714221781    0.3370719316    0.3448775575    0.4680917054    0.5522485803    0.2508875918    0.2605494236    0.3328528435    0.5029657219    0.3350600118    0.3525144029    0.4675220634    0.5508751864    0.2470085671    0.2591043240    0.3318206753    0.5029230613        0.2378259019    0.2393538803    0.3202736101    0.4966865614    0.0820879900    0.0771501767    0.0693680136    0.4500522355    0.2423923928    0.2444231931    0.326022839,    0.498913233,    0.0735200285    0.0687001795    0.0557053413    0.4497154037    0.2249825099    0.2299975550    0.29332317950.4875778905    0.5730721526    0.5736709561    0.8359746316    0.7715416324
65536   0.3315472704    0.3098758872    0.2948799957    1.3761097766    0.5705455540    0.546376473,    0.5520997747    1.434775142,    0.4373900432    0.4173965980    0.4124995413    1.3771025894    0.56516633,     0.5422310254    0.5638459012    1.4331749806    0.4320985907    0.4018881601    0.4241962276    1.3821499741        0.4018703646    0.3250932425    0.3311144942    1.3793404691    0.1514260072    0.1310092632    0.1143757240    1.3390705802    0.4059789234    0.3288167702    0.3342683949    1.3660338475    0.1376183222    0.1222059192    0.1025875349    1.3396406151    0.3876408274    0.3710101261    0.36775827581.3735223842    0.9353710327    0.9247489474    0.9682498708    1.5596118862
262144  1.2056974120    1.1333602531    1.0877623781    5.2022942798    2.1232045222    2.1856630589    2.1573226186    5.5379055972    1.6192330488    1.6053534100    1.5612246114    5.3700376861    2.1164048981    2.1908843424    2.1346249812    5.5585556694    1.6006847373    1.5883122461    1.5491111198    5.3424273220        1.4909280746    1.1902887666    1.1542709407    5.3183265135    0.5116285099    0.4056088303    0.3537193156    4.919325751,    1.5094776240    1.2076485366    1.1674740388    5.2965400409    0.4528506094    0.3835686186    0.3477171890    4.9197883140    1.4513691900    1.3662113826    1.33037584885.3359084009    3.5708873235    3.9924629163    3.9562677946    5.9412578627
586011  2.8843384640    3.1479987014    2.9940223690    12.489745648    5.6601261454    6.2149173557    6.0004215437    12.770064618    3.9773940554    4.4483697571    4.3002161132    12.697794081    5.6523621429    6.2165891872    5.9990755805    12.649486261    4.0367221610    4.4300985954    4.2925374729    12.705934805        3.5637802827    3.5937352341    3.5551168281    12.521177536    0.9937906061    0.8918547401    0.8531092863    11.614712179    3.6907495999    3.6831788480    3.6318771806    12.648930436    0.8594042205    0.8105772717    0.7623861305    11.454705475    3.4807875060    3.8212284663    3.688166017312.620083305    10.289389616    11.367691732    10.931462497    14.674622038

-----------------------------------------------------
-------------------- "max" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0737654973    0.0739302373    0.0801992223    0.2013681373    0.1205229872    0.1174084282    0.1479210512    0.2630326542    0.0950117055    0.0921173975    0.1086515965    0.2266276135    0.1194914708    0.1196527768    0.1513599438    0.2655955858    0.0951511192    0.0932618332    0.1079756052    0.2301628322        0.0902040910    0.0908250650    0.1063539770    0.2217860410    0.0396532189    0.0390039809    0.0304364039    0.1761307589    0.0909991854    0.0908157554    0.1045240774    0.2234759244    0.0384744452    0.0368485122    0.0264665162    0.1778595592    0.0845160974    0.0833906094    0.09689096940.2153988074    0.1949540872    0.1901945872    0.2630900082    0.3654690232
4096    0.0686133367    0.0664027767    0.0611148187    0.2263980967    0.1004387927    0.1010815637    0.0994637107    0.2305676507    0.0843000613    0.0801488743    0.0830314333    0.2278618593    0.1004973312    0.0957231122    0.0996421942    0.2312011692    0.0824919177    0.0790956557    0.0774494977    0.2260153947        0.0795441131    0.0769729701    0.0739844601    0.2256075511    0.0452637663    0.0456879113    0.0321892983    0.2268949033    0.0804496337    0.0766309287    0.0743937867    0.2281625037    0.0439190586    0.0420368926    0.0285038696    0.2258741586    0.0781215302    0.0851812802    0.07301866420.2241731722    0.1480952160    0.1412784280    0.1597617440    0.2702111820
16384   0.2047424389    0.2110830209    0.2409090219    0.4746982719    0.3692640846    0.3768285346    0.4692409516    0.5543894356    0.2760481034    0.2797509594    0.3340928564    0.5084180444    0.3548096938    0.3861784098    0.4691970808    0.5522347308    0.2482935328    0.3006845778    0.3334153728    0.5078348088        0.2406195336    0.2444148906    0.3292839726    0.5019151316    0.0845794590    0.0834336430    0.0705959140    0.4532124540    0.2540124921    0.2546572401    0.3375237081    0.5013783781    0.0778815298    0.0777161628    0.0568031658    0.4520128058    0.2409462580    0.2524052430    0.29423269900.4910468240    0.5742561919    0.5780721909    0.8651931839    0.7884782109
65536   0.3560441213    0.3282847703    0.3079204573    1.4102522583    0.5856834077    0.5827994507    0.5728979977    1.4617257426    0.4635744035    0.4513609945    0.4383685565    1.3919640735    0.5897912918    0.5756986808    0.5867632828    1.4517351498    0.4643912304    0.4296369744    0.4574314344    1.4101401204        0.4045499703    0.3423141603    0.3451978343    1.4057902223    0.1546492755    0.1379673425    0.1266040795    1.3541963945    0.4100557626    0.3453473436    0.3463700586    1.3823045786    0.1417221179    0.1287446559    0.1115949389    1.3843839509    0.3982034993    0.3856765723    0.38583961131.3813225273    0.9481710927    0.9568718127    0.9953749277    1.5717940367
262144  1.2131263969    1.1622785069    1.1739707669    5.2382096549    2.1425232165    2.2123762225    2.2003994235    5.6159088455    1.6292023998    1.6556210578    1.5897021008    5.4689087388    2.1269788491    2.2131559520    2.1692098311    5.7275714661    1.6107867014    1.6285726184    1.5756968224    5.4080304124        1.4957382608    1.2269232518    1.1723977398    5.3649952097    0.5142118907    0.4133380697    0.3635367727    4.9533462807    1.5178901370    1.2298254520    1.1781307300    5.4082369680    0.4556401492    0.3859902382    0.3578487212    5.0506026162    1.4627078075    1.3965456045    1.35330458655.4693873385    3.5857523021    4.0346550591    4.0139707971    6.0138307301
586011  3.1538495492    3.1940435552    3.0436338192    12.971055986    5.8499547391    6.2431176151    6.1567952101    13.188993070    4.2619106864    4.4759434054    4.4371111874    12.951725322    6.3838991605    6.2698050135    6.0999977165    12.959883048    4.4787631115    4.4696177635    4.4182574945    13.031016792        3.5904352163    3.6244958133    3.6239126653    12.738832295    1.0318662296    0.9128433976    0.8868486886    11.885069127    3.7794067079    3.7098709299    3.7076383089    12.936725692    0.8798181666    0.8288777846    0.7701301796    11.747105727    3.8357183723    3.8734066553    3.747639360313.009199828    11.686702079    11.706485601    11.190667492    14.863016572


||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0730518678    0.0726516056    0.0792227436    0.1982759592    forkrun is 9.044% faster than xargs (1.0904x)   forkrun is 172.9% faster than parallel (2.7291x)
sha256sum       0.1181867048    0.1167904776    0.1463040885    0.2626038960    forkrun is 23.79% faster than xargs (1.2379x)   forkrun is 122.1% faster than parallel (2.2219x)
sha512sum       0.0915359840    0.0908748963    0.1076036246    0.2252557624    forkrun is 18.40% faster than xargs (1.1840x)   forkrun is 147.8% faster than parallel (2.4787x)
sha224sum       0.1179767674    0.1172630170    0.1460100702    0.2632914574    forkrun is 24.51% faster than xargs (1.2451x)   forkrun is 124.5% faster than parallel (2.2453x)
sha384sum       0.0913766370    0.0906554735    0.1069279112    0.2256200863    forkrun is 17.94% faster than xargs (1.1794x)   forkrun is 148.8% faster than parallel (2.4887x)
md5sum          0.0890722645    0.0885602411    0.1025294036    0.2208817104    forkrun is 15.77% faster than xargs (1.1577x)   forkrun is 149.4% faster than parallel (2.4941x)
sum -s          0.0384651880    0.0377418936    0.0295401546    0.1744338733    xargs is 27.76% faster than forkrun (1.2776x)   forkrun is 362.1% faster than parallel (4.6217x)
sum -r          0.0904119870    0.0890912982    0.1036866706    0.2222509364    forkrun is 16.38% faster than xargs (1.1638x)   forkrun is 149.4% faster than parallel (2.4946x)
cksum           0.0359033759    0.0358492843    0.0252940136    0.1749671145    xargs is 41.94% faster than forkrun (1.4194x)   forkrun is 387.3% faster than parallel (4.8732x)
b2sum           0.0837604766    0.0824591534    0.0956487950    0.2141598351    forkrun is 15.99% faster than xargs (1.1599x)   forkrun is 159.7% faster than parallel (2.5971x)
cksum -a sm3    0.189431657     0.1872982812    0.2525056671    0.364440035     forkrun is 33.29% faster than xargs (1.3329x)   forkrun is 92.38% faster than parallel (1.9238x)

OVERALL         1.0191729105    1.0092356224    1.1952731432    2.5461806665    forkrun is 18.43% faster than xargs (1.1843x)   forkrun is 152.2% faster than parallel (2.5228x)




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0668608090    0.0636300662    0.0596535882    0.2235040673    xargs is 6.665% faster than forkrun (1.0666x)   forkrun is 251.2% faster than parallel (3.5125x)
sha256sum       0.0971956319    0.0920190336    0.0983732376    0.2294493408    forkrun is 6.905% faster than xargs (1.0690x)   forkrun is 149.3% faster than parallel (2.4934x)
sha512sum       0.0809913311    0.0764260806    0.0785435763    0.2232483140    forkrun is 2.770% faster than xargs (1.0277x)   forkrun is 192.1% faster than parallel (2.9211x)
sha224sum       0.0967508951    0.0918358612    0.0980551429    0.2296537546    forkrun is 6.772% faster than xargs (1.0677x)   forkrun is 150.0% faster than parallel (2.5006x)
sha384sum       0.0802556491    0.0759840288    0.0769347817    0.2235948712    forkrun is 1.251% faster than xargs (1.0125x)   forkrun is 194.2% faster than parallel (2.9426x)
md5sum          0.0773295460    0.0737700811    0.0726324909    0.2234840200    xargs is 1.566% faster than forkrun (1.0156x)   forkrun is 202.9% faster than parallel (3.0294x)
sum -s          0.0447589359    0.0424078085    0.0313619292    0.2242520554    xargs is 35.22% faster than forkrun (1.3522x)   forkrun is 428.7% faster than parallel (5.2879x)
sum -r          0.0779810405    0.0741920094    0.0729668465    0.2241976680    xargs is 1.679% faster than forkrun (1.0167x)   forkrun is 202.1% faster than parallel (3.0218x)
cksum           0.0424533731    0.0403091835    0.0278372356    0.2248445139    xargs is 44.80% faster than forkrun (1.4480x)   forkrun is 457.7% faster than parallel (5.5779x)
b2sum           0.0757823090    0.0726048154    0.0713034696    0.2231194351    xargs is 1.825% faster than forkrun (1.0182x)   forkrun is 207.3% faster than parallel (3.0730x)
cksum -a sm3    0.1435031647    0.1352685762    0.1589066921    0.2686105604    forkrun is 17.47% faster than xargs (1.1747x)   forkrun is 98.57% faster than parallel (1.9857x)

OVERALL         .88386268596    .83844754498    .84656899126    2.5179586012    forkrun is .9686% faster than xargs (1.0096x)   forkrun is 200.3% faster than parallel (3.0031x)




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.1910319961    0.1909195783    0.2395306548    0.4714221781    forkrun is 25.46% faster than xargs (1.2546x)   forkrun is 146.9% faster than parallel (2.4692x)
sha256sum       0.3370719316    0.3448775575    0.4680917054    0.5522485803    forkrun is 38.86% faster than xargs (1.3886x)   forkrun is 63.83% faster than parallel (1.6383x)
sha512sum       0.2508875918    0.2605494236    0.3328528435    0.5029657219    forkrun is 32.67% faster than xargs (1.3267x)   forkrun is 100.4% faster than parallel (2.0047x)
sha224sum       0.3350600118    0.3525144029    0.4675220634    0.5508751864    forkrun is 32.62% faster than xargs (1.3262x)   forkrun is 56.27% faster than parallel (1.5627x)
sha384sum       0.2470085671    0.2591043240    0.3318206753    0.5029230613    forkrun is 34.33% faster than xargs (1.3433x)   forkrun is 103.6% faster than parallel (2.0360x)
md5sum          0.2378259019    0.2393538803    0.3202736101    0.4966865614    forkrun is 34.66% faster than xargs (1.3466x)   forkrun is 108.8% faster than parallel (2.0884x)
sum -s          0.0820879900    0.0771501767    0.0693680136    0.4500522355    xargs is 11.21% faster than forkrun (1.1121x)   forkrun is 483.3% faster than parallel (5.8334x)
sum -r          0.2423923928    0.2444231931    0.326022839     0.498913233     forkrun is 34.50% faster than xargs (1.3450x)   forkrun is 105.8% faster than parallel (2.0582x)
cksum           0.0735200285    0.0687001795    0.0557053413    0.4497154037    xargs is 23.32% faster than forkrun (1.2332x)   forkrun is 554.6% faster than parallel (6.5460x)
b2sum           0.2249825099    0.2299975550    0.2933231795    0.4875778905    forkrun is 30.37% faster than xargs (1.3037x)   forkrun is 116.7% faster than parallel (2.1671x)
cksum -a sm3    0.5730721526    0.5736709561    0.8359746316    0.7715416324    forkrun is 45.87% faster than xargs (1.4587x)   forkrun is 34.63% faster than parallel (1.3463x)

OVERALL         2.7949410745    2.8412612275    3.7404855579    5.7349216849    forkrun is 33.83% faster than xargs (1.3383x)   forkrun is 105.1% faster than parallel (2.0518x)




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.3315472704    0.3098758872    0.2948799957    1.3761097766    xargs is 5.085% faster than forkrun (1.0508x)   forkrun is 344.0% faster than parallel (4.4408x)
sha256sum       0.5705455540    0.546376473     0.5520997747    1.434775142     forkrun is 1.047% faster than xargs (1.0104x)   forkrun is 162.5% faster than parallel (2.6259x)
sha512sum       0.4373900432    0.4173965980    0.4124995413    1.3771025894    xargs is 6.034% faster than forkrun (1.0603x)   forkrun is 214.8% faster than parallel (3.1484x)
sha224sum       0.56516633      0.5422310254    0.5638459012    1.4331749806    xargs is .2341% faster than forkrun (1.0023x)   forkrun is 153.5% faster than parallel (2.5358x)
sha384sum       0.4320985907    0.4018881601    0.4241962276    1.3821499741    forkrun is 5.550% faster than xargs (1.0555x)   forkrun is 243.9% faster than parallel (3.4391x)
md5sum          0.4018703646    0.3250932425    0.3311144942    1.3793404691    forkrun is 1.852% faster than xargs (1.0185x)   forkrun is 324.2% faster than parallel (4.2429x)
sum -s          0.1514260072    0.1310092632    0.1143757240    1.3390705802    xargs is 14.54% faster than forkrun (1.1454x)   forkrun is 922.1% faster than parallel (10.221x)
sum -r          0.4059789234    0.3288167702    0.3342683949    1.3660338475    forkrun is 1.657% faster than xargs (1.0165x)   forkrun is 315.4% faster than parallel (4.1543x)
cksum           0.1376183222    0.1222059192    0.1025875349    1.3396406151    xargs is 19.12% faster than forkrun (1.1912x)   forkrun is 996.2% faster than parallel (10.962x)
b2sum           0.3876408274    0.3710101261    0.3677582758    1.3735223842    xargs is .8842% faster than forkrun (1.0088x)   forkrun is 270.2% faster than parallel (3.7021x)
cksum -a sm3    0.9353710327    0.9247489474    0.9682498708    1.5596118862    forkrun is 4.704% faster than xargs (1.0470x)   forkrun is 68.65% faster than parallel (1.6865x)

OVERALL         4.7566532661    4.4206524126    4.4658757354    15.360532245    forkrun is 1.023% faster than xargs (1.0102x)   forkrun is 247.4% faster than parallel (3.4747x)




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         1.2056974120    1.1333602531    1.0877623781    5.2022942798    xargs is 4.191% faster than forkrun (1.0419x)   forkrun is 359.0% faster than parallel (4.5901x)
sha256sum       2.1232045222    2.1856630589    2.1573226186    5.5379055972    forkrun is 1.606% faster than xargs (1.0160x)   forkrun is 160.8% faster than parallel (2.6082x)
sha512sum       1.6192330488    1.6053534100    1.5612246114    5.3700376861    xargs is 2.826% faster than forkrun (1.0282x)   forkrun is 234.5% faster than parallel (3.3450x)
sha224sum       2.1164048981    2.1908843424    2.1346249812    5.5585556694    forkrun is .8608% faster than xargs (1.0086x)   forkrun is 162.6% faster than parallel (2.6264x)
sha384sum       1.6006847373    1.5883122461    1.5491111198    5.3424273220    xargs is 2.530% faster than forkrun (1.0253x)   forkrun is 236.3% faster than parallel (3.3635x)
md5sum          1.4909280746    1.1902887666    1.1542709407    5.3183265135    xargs is 29.16% faster than forkrun (1.2916x)   forkrun is 256.7% faster than parallel (3.5671x)
sum -s          0.5116285099    0.4056088303    0.3537193156    4.919325751     xargs is 14.66% faster than forkrun (1.1466x)   forkrun is 1112.% faster than parallel (12.128x)
sum -r          1.5094776240    1.2076485366    1.1674740388    5.2965400409    xargs is 3.441% faster than forkrun (1.0344x)   forkrun is 338.5% faster than parallel (4.3858x)
cksum           0.4528506094    0.3835686186    0.3477171890    4.9197883140    xargs is 10.31% faster than forkrun (1.1031x)   forkrun is 1182.% faster than parallel (12.826x)
b2sum           1.4513691900    1.3662113826    1.3303758488    5.3359084009    xargs is 2.693% faster than forkrun (1.0269x)   forkrun is 290.5% faster than parallel (3.9056x)
cksum -a sm3    3.5708873235    3.9924629163    3.9562677946    5.9412578627    forkrun is 10.79% faster than xargs (1.1079x)   forkrun is 66.38% faster than parallel (1.6638x)

OVERALL         17.652365950    17.249362362    16.799870837    58.742367437    xargs is 2.675% faster than forkrun (1.0267x)   forkrun is 240.5% faster than parallel (3.4054x)




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         2.8843384640    3.1479987014    2.9940223690    12.489745648    forkrun is 3.802% faster than xargs (1.0380x)   forkrun is 333.0% faster than parallel (4.3301x)
sha256sum       5.6601261454    6.2149173557    6.0004215437    12.770064618    forkrun is 6.012% faster than xargs (1.0601x)   forkrun is 125.6% faster than parallel (2.2561x)
sha512sum       3.9773940554    4.4483697571    4.3002161132    12.697794081    forkrun is 8.116% faster than xargs (1.0811x)   forkrun is 219.2% faster than parallel (3.1924x)
sha224sum       5.6523621429    6.2165891872    5.9990755805    12.649486261    forkrun is 6.133% faster than xargs (1.0613x)   forkrun is 123.7% faster than parallel (2.2379x)
sha384sum       4.0367221610    4.4300985954    4.2925374729    12.705934805    forkrun is 6.337% faster than xargs (1.0633x)   forkrun is 214.7% faster than parallel (3.1475x)
md5sum          3.5637802827    3.5937352341    3.5551168281    12.521177536    xargs is .2436% faster than forkrun (1.0024x)   forkrun is 251.3% faster than parallel (3.5134x)
sum -s          0.9937906061    0.8918547401    0.8531092863    11.614712179    xargs is 4.541% faster than forkrun (1.0454x)   forkrun is 1202.% faster than parallel (13.023x)
sum -r          3.6907495999    3.6831788480    3.6318771806    12.648930436    xargs is 1.412% faster than forkrun (1.0141x)   forkrun is 243.4% faster than parallel (3.4342x)
cksum           0.8594042205    0.8105772717    0.7623861305    11.454705475    xargs is 6.321% faster than forkrun (1.0632x)   forkrun is 1313.% faster than parallel (14.131x)
b2sum           3.4807875060    3.8212284663    3.6881660173    12.620083305    forkrun is 5.957% faster than xargs (1.0595x)   forkrun is 262.5% faster than parallel (3.6256x)
cksum -a sm3    10.289389616    11.367691732    10.931462497    14.674622038    forkrun is 6.240% faster than xargs (1.0624x)   forkrun is 42.61% faster than parallel (1.4261x)

OVERALL         45.088844801    48.626239890    47.008391020    138.84725638    forkrun is 4.257% faster than xargs (1.0425x)   forkrun is 207.9% faster than parallel (3.0794x)


-------------------------------- 1024 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha1sum  | wc -l
 
  Warning  Time (mean ± σ):      73.2 ms ±   0.5 ms    [User: 91.2 ms, System: 43.2 ms]
  Range (min … max):    72.8 ms …  76.0 ms    39 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha1sum  | wc -l
  Time (mean ± σ):      72.7 ms ±   0.3 ms    [User: 93.1 ms, System: 47.9 ms]
  Range (min … max):    72.1 ms …  73.8 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l
  Time (mean ± σ):      79.5 ms ±   0.4 ms    [User: 64.8 ms, System: 18.6 ms]
  Range (min … max):    78.8 ms …  80.7 ms    36 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha1sum  | wc -l
  Time (mean ± σ):     198.2 ms ±   0.8 ms    [User: 214.5 ms, System: 146.2 ms]
  Range (min … max):   196.8 ms … 199.5 ms    14 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha1sum  | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha1sum  | wc -l
    1.09 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l
    2.73 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha1sum  | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha256sum  | wc -l
  Time (mean ± σ):     117.9 ms ±   0.5 ms    [User: 156.6 ms, System: 45.3 ms]
  Range (min … max):   117.1 ms … 119.5 ms    24 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha256sum  | wc -l
  Time (mean ± σ):     117.0 ms ±   0.6 ms    [User: 162.3 ms, System: 46.6 ms]
  Range (min … max):   116.0 ms … 118.5 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
  Time (mean ± σ):     146.1 ms ±   0.8 ms    [User: 132.3 ms, System: 17.8 ms]
  Range (min … max):   145.0 ms … 148.6 ms    19 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha256sum  | wc -l
  Time (mean ± σ):     263.2 ms ±   0.7 ms    [User: 286.5 ms, System: 143.4 ms]
  Range (min … max):   262.0 ms … 264.1 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha256sum  | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha256sum  | wc -l
    1.25 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
    2.25 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha256sum  | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha512sum  | wc -l
  Time (mean ± σ):      91.4 ms ±   0.3 ms    [User: 120.7 ms, System: 42.5 ms]
  Range (min … max):    90.7 ms …  92.1 ms    31 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha512sum  | wc -l
  Time (mean ± σ):      90.8 ms ±   0.4 ms    [User: 123.9 ms, System: 46.3 ms]
  Range (min … max):    90.2 ms …  91.9 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     108.0 ms ±   0.8 ms    [User: 93.6 ms, System: 18.4 ms]
  Range (min … max):   107.3 ms … 111.4 ms    26 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha512sum  | wc -l
  Time (mean ± σ):     225.6 ms ±   0.6 ms    [User: 247.6 ms, System: 142.7 ms]
  Range (min … max):   224.3 ms … 226.6 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha512sum  | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha512sum  | wc -l
    1.19 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l
    2.48 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha512sum  | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha224sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.  Time (mean ± σ):     119.0 ms ±   4.5 ms    [User: 157.8 ms, System: 45.1 ms]
  Range (min … max):   117.3 ms … 140.2 ms    24 runs

 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha224sum  | wc -l
  Time (mean ± σ):     117.3 ms ±   0.9 ms    [User: 160.7 ms, System: 48.1 ms]
  Range (min … max):   116.1 ms … 121.0 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
  Time (mean ± σ):     146.3 ms ±   0.7 ms    [User: 132.4 ms, System: 17.9 ms]
  Range (min … max):   145.5 ms … 147.7 ms    19 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha224sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     263.2 ms ±   2.0 ms    [User: 279.9 ms, System: 149.3 ms]
  Range (min … max):   261.4 ms … 269.0 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha224sum  | wc -l ran
    1.01 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha224sum  | wc -l
    1.25 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
    2.24 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha224sum  | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha384sum  | wc -l
 
    Time (mean ± σ):      91.3 ms ±   0.7 ms    [User: 120.0 ms, System: 42.6 ms]
  Range (min … max):    90.6 ms …  94.7 ms    31 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha384sum  | wc -l
  Time (mean ± σ):      90.6 ms ±   0.3 ms    [User: 121.6 ms, System: 47.7 ms]
  Range (min … max):    90.1 ms …  91.3 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
  Time (mean ± σ):     107.0 ms ±   0.4 ms    [User: 93.5 ms, System: 17.5 ms]
  Range (min … max):   106.4 ms … 108.0 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha384sum  | wc -l
  Time (mean ± σ):     225.0 ms ±   0.7 ms    [User: 241.0 ms, System: 148.1 ms]
  Range (min … max):   224.4 ms … 226.5 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha384sum  | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha384sum  | wc -l
    1.18 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
    2.48 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha384sum  | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- md5sum  | wc -l
  Time (mean ± σ):      89.2 ms ±   0.3 ms    [User: 114.1 ms, System: 44.0 ms]
  Range (min … max):    88.5 ms …  90.0 ms    32 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- md5sum  | wc -l
 
    Time (mean ± σ):      88.7 ms ±   0.5 ms    [User: 117.8 ms, System: 46.7 ms]
  Range (min … max):    88.1 ms …  90.7 ms    32 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l
  Time (mean ± σ):     102.6 ms ±   0.3 ms    [User: 88.4 ms, System: 18.2 ms]
  Range (min … max):   101.8 ms … 103.3 ms    28 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- md5sum  | wc -l
  Time (mean ± σ):     221.3 ms ±   1.0 ms    [User: 234.3 ms, System: 150.4 ms]
  Range (min … max):   220.2 ms … 224.3 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- md5sum  | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- md5sum  | wc -l
    1.16 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l
    2.50 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- md5sum  | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -s  | wc -l
  Time (mean ± σ):      38.5 ms ±   0.2 ms    [User: 40.6 ms, System: 40.4 ms]
  Range (min … max):    38.2 ms …  39.0 ms    71 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -s  | wc -l
  Time (mean ± σ):      37.8 ms ±   0.3 ms    [User: 40.6 ms, System: 44.0 ms]
  Range (min … max):    37.3 ms …  39.3 ms    72 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l
  Time (mean ± σ):      29.8 ms ±   0.2 ms    [User: 16.2 ms, System: 17.7 ms]
  Range (min … max):    29.3 ms …  30.7 ms    90 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -s  | wc -l
  Time (mean ± σ):     174.4 ms ±   0.9 ms    [User: 162.1 ms, System: 136.6 ms]
  Range (min … max):   172.4 ms … 175.4 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l ran
    1.27 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -s  | wc -l
    1.29 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -s  | wc -l
    5.86 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -s  | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -r  | wc -l
  Time (mean ± σ):      90.3 ms ±   0.3 ms    [User: 115.4 ms, System: 41.8 ms]
  Range (min … max):    89.5 ms …  91.2 ms    32 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -r  | wc -l
  Time (mean ± σ):      89.2 ms ±   0.5 ms    [User: 118.8 ms, System: 43.8 ms]
  Range (min … max):    88.5 ms …  90.3 ms    32 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l
  Time (mean ± σ):     103.7 ms ±   0.3 ms    [User: 91.6 ms, System: 16.1 ms]
  Range (min … max):   103.0 ms … 104.6 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -r  | wc -l
  Time (mean ± σ):     222.4 ms ±   0.8 ms    [User: 233.9 ms, System: 141.2 ms]
  Range (min … max):   221.4 ms … 224.0 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -r  | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -r  | wc -l
    1.16 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l
    2.49 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -r  | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum  | wc -l
  Time (mean ± σ):      35.9 ms ±   0.3 ms    [User: 36.2 ms, System: 42.2 ms]
  Range (min … max):    35.5 ms …  37.3 ms    75 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum  | wc -l
  Time (mean ± σ):      35.9 ms ±   0.2 ms    [User: 39.0 ms, System: 46.4 ms]
  Range (min … max):    35.6 ms …  36.6 ms    75 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum  | wc -l
  Time (mean ± σ):      25.4 ms ±   0.2 ms    [User: 11.9 ms, System: 17.7 ms]
  Range (min … max):    24.8 ms …  26.2 ms    103 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum  | wc -l
  Time (mean ± σ):     175.2 ms ±   0.9 ms    [User: 159.5 ms, System: 147.3 ms]
  Range (min … max):   173.5 ms … 176.7 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum  | wc -l ran
    1.41 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum  | wc -l
    1.42 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum  | wc -l
    6.90 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum  | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- b2sum  | wc -l
  Time (mean ± σ):      83.8 ms ±   0.4 ms    [User: 108.6 ms, System: 40.8 ms]
  Range (min … max):    83.0 ms …  84.9 ms    34 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- b2sum  | wc -l
  Time (mean ± σ):      82.6 ms ±   0.4 ms    [User: 108.6 ms, System: 45.9 ms]
  Range (min … max):    81.5 ms …  83.5 ms    34 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l
  Time (mean ± σ):      96.0 ms ±   0.4 ms    [User: 81.2 ms, System: 18.8 ms]
  Range (min … max):    95.3 ms …  96.7 ms    30 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- b2sum  | wc -l
  Time (mean ± σ):     214.3 ms ±   0.7 ms    [User: 226.3 ms, System: 140.7 ms]
  Range (min … max):   213.5 ms … 215.7 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- b2sum  | wc -l ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- b2sum  | wc -l
    1.16 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l
    2.60 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- b2sum  | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum -a sm3  | wc -l
  Time (mean ± σ):     188.9 ms ±   0.4 ms    [User: 265.5 ms, System: 43.4 ms]
  Range (min … max):   188.3 ms … 190.0 ms    15 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum -a sm3  | wc -l
  Time (mean ± σ):     187.5 ms ±   0.8 ms    [User: 270.0 ms, System: 48.3 ms]
  Range (min … max):   186.4 ms … 189.7 ms    15 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
  Time (mean ± σ):     252.7 ms ±   2.6 ms    [User: 237.2 ms, System: 19.3 ms]
  Range (min … max):   250.9 ms … 260.3 ms    11 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum -a sm3  | wc -l
  Time (mean ± σ):     364.6 ms ±   0.7 ms    [User: 390.7 ms, System: 145.7 ms]
  Range (min … max):   363.2 ms … 365.4 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum -a sm3  | wc -l ran
    1.01 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum -a sm3  | wc -l
    1.35 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
    1.94 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum -a sm3  | wc -l

-------------------------------- 4096 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha1sum  | wc -l
  Time (mean ± σ):      67.0 ms ±   0.6 ms    [User: 124.6 ms, System: 67.3 ms]
  Range (min … max):    66.4 ms …  68.9 ms    41 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha1sum  | wc -l
  Time (mean ± σ):      63.7 ms ±   1.3 ms    [User: 125.1 ms, System: 70.9 ms]
  Range (min … max):    61.9 ms …  66.6 ms    44 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l
  Time (mean ± σ):      59.9 ms ±   0.3 ms    [User: 92.8 ms, System: 42.5 ms]
  Range (min … max):    59.4 ms …  61.1 ms    47 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha1sum  | wc -l
  Time (mean ± σ):     224.1 ms ±   1.1 ms    [User: 293.2 ms, System: 168.7 ms]
  Range (min … max):   222.5 ms … 226.3 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l ran
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha1sum  | wc -l
    1.12 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha1sum  | wc -l
    3.74 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha1sum  | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha256sum  | wc -l
  Time (mean ± σ):      97.1 ms ±   1.3 ms    [User: 207.4 ms, System: 69.6 ms]
  Range (min … max):    94.5 ms … 100.1 ms    30 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha256sum  | wc -l
  Time (mean ± σ):      92.0 ms ±   1.8 ms    [User: 211.2 ms, System: 71.9 ms]
  Range (min … max):    90.4 ms …  96.5 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
  Time (mean ± σ):      98.6 ms ±   0.5 ms    [User: 175.6 ms, System: 42.8 ms]
  Range (min … max):    97.9 ms … 100.5 ms    29 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha256sum  | wc -l
  Time (mean ± σ):     230.1 ms ±   0.9 ms    [User: 374.9 ms, System: 173.3 ms]
  Range (min … max):   228.7 ms … 231.4 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha256sum  | wc -l ran
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha256sum  | wc -l
    1.07 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
    2.50 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha256sum  | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha512sum  | wc -l
  Time (mean ± σ):      81.2 ms ±   1.0 ms    [User: 165.5 ms, System: 69.0 ms]
  Range (min … max):    80.3 ms …  83.7 ms    35 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha512sum  | wc -l
 
  Warning  Time (mean ± σ):      76.7 ms ±   2.3 ms    [User: 169.7 ms, System: 70.2 ms]
  Range (min … max):    75.1 ms …  87.7 ms    37 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l
  Time (mean ± σ):      78.6 ms ±   0.3 ms    [User: 132.8 ms, System: 44.1 ms]
  Range (min … max):    78.1 ms …  79.5 ms    36 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha512sum  | wc -l
  Time (mean ± σ):     223.5 ms ±   2.1 ms    [User: 335.0 ms, System: 169.6 ms]
  Range (min … max):   220.8 ms … 227.5 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha512sum  | wc -l ran
    1.02 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l
    1.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha512sum  | wc -l
    2.91 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha512sum  | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha224sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      97.5 ms ±   2.5 ms    [User: 207.5 ms, System: 69.2 ms]
  Range (min … max):    96.0 ms … 109.1 ms    30 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha224sum  | wc -l
 
  Warning  Time (mean ± σ):      91.3 ms ±   1.2 ms    [User: 209.2 ms, System: 70.5 ms]
  Range (min … max):    90.2 ms …  95.7 ms    31 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      98.2 ms ±   0.8 ms    [User: 176.4 ms, System: 41.1 ms]
  Range (min … max):    97.5 ms … 102.3 ms    29 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha224sum  | wc -l
  Time (mean ± σ):     229.9 ms ±   0.9 ms    [User: 376.9 ms, System: 170.1 ms]
  Range (min … max):   228.3 ms … 231.5 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha224sum  | wc -l ran
    1.07 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha224sum  | wc -l
    1.08 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
    2.52 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha224sum  | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha384sum  | wc -l
  Time (mean ± σ):      80.3 ms ±   0.8 ms    [User: 163.6 ms, System: 67.7 ms]
  Range (min … max):    79.3 ms …  82.5 ms    35 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha384sum  | wc -l
  Time (mean ± σ):      75.8 ms ±   1.2 ms    [User: 164.3 ms, System: 70.6 ms]
  Range (min … max):    74.5 ms …  79.4 ms    37 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
  Time (mean ± σ):      77.2 ms ±   0.4 ms    [User: 130.2 ms, System: 43.1 ms]
  Range (min … max):    76.5 ms …  78.3 ms    37 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha384sum  | wc -l
  Time (mean ± σ):     224.8 ms ±   1.8 ms    [User: 328.2 ms, System: 174.0 ms]
  Range (min … max):   221.6 ms … 228.0 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha384sum  | wc -l ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha384sum  | wc -l
    2.97 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha384sum  | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- md5sum  | wc -l
  Time (mean ± σ):      77.2 ms ±   0.5 ms    [User: 151.5 ms, System: 68.5 ms]
  Range (min … max):    76.5 ms …  79.5 ms    37 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- md5sum  | wc -l
  Time (mean ± σ):      73.4 ms ±   1.6 ms    [User: 152.1 ms, System: 71.8 ms]
  Range (min … max):    69.4 ms …  76.8 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l
  Time (mean ± σ):      72.9 ms ±   0.3 ms    [User: 119.1 ms, System: 43.7 ms]
  Range (min … max):    72.4 ms …  73.7 ms    39 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- md5sum  | wc -l
  Time (mean ± σ):     223.7 ms ±   1.1 ms    [User: 319.8 ms, System: 170.0 ms]
  Range (min … max):   221.8 ms … 225.7 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- md5sum  | wc -l
    1.06 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- md5sum  | wc -l
    3.07 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- md5sum  | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -s  | wc -l
  Time (mean ± σ):      44.9 ms ±   0.2 ms    [User: 62.8 ms, System: 62.6 ms]
  Range (min … max):    44.5 ms …  45.8 ms    61 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -s  | wc -l
  Time (mean ± σ):      42.8 ms ±   0.9 ms    [User: 64.0 ms, System: 66.5 ms]
  Range (min … max):    41.8 ms …  45.3 ms    65 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l
  Time (mean ± σ):      31.5 ms ±   0.2 ms    [User: 33.1 ms, System: 40.0 ms]
  Range (min … max):    31.1 ms …  32.3 ms    86 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -s  | wc -l
  Time (mean ± σ):     224.1 ms ±   1.0 ms    [User: 227.7 ms, System: 164.5 ms]
  Range (min … max):   222.8 ms … 226.1 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l ran
    1.36 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -s  | wc -l
    1.43 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -s  | wc -l
    7.12 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -s  | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -r  | wc -l
  Time (mean ± σ):      78.0 ms ±   0.3 ms    [User: 153.6 ms, System: 63.5 ms]
  Range (min … max):    77.3 ms …  78.6 ms    36 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -r  | wc -l
  Time (mean ± σ):      74.1 ms ±   1.6 ms    [User: 154.1 ms, System: 67.9 ms]
  Range (min … max):    70.4 ms …  77.1 ms    40 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l
  Time (mean ± σ):      73.1 ms ±   0.4 ms    [User: 121.2 ms, System: 41.8 ms]
  Range (min … max):    72.5 ms …  74.1 ms    39 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -r  | wc -l
  Time (mean ± σ):     223.8 ms ±   1.6 ms    [User: 316.4 ms, System: 163.9 ms]
  Range (min … max):   222.1 ms … 228.3 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -r  | wc -l
    1.07 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -r  | wc -l
    3.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -r  | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum  | wc -l
  Time (mean ± σ):      42.5 ms ±   0.4 ms    [User: 55.6 ms, System: 64.7 ms]
  Range (min … max):    41.8 ms …  44.7 ms    62 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum  | wc -l
  Time (mean ± σ):      40.3 ms ±   0.6 ms    [User: 55.2 ms, System: 68.6 ms]
  Range (min … max):    39.6 ms …  42.3 ms    68 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum  | wc -l
  Time (mean ± σ):      27.9 ms ±   0.2 ms    [User: 24.4 ms, System: 40.4 ms]
  Range (min … max):    27.4 ms …  28.5 ms    95 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum  | wc -l
  Time (mean ± σ):     225.0 ms ±   1.6 ms    [User: 224.8 ms, System: 170.9 ms]
  Range (min … max):   223.3 ms … 229.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum  | wc -l ran
    1.44 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum  | wc -l
    1.52 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum  | wc -l
    8.05 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum  | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- b2sum  | wc -l
  Time (mean ± σ):      75.9 ms ±   0.4 ms    [User: 151.2 ms, System: 63.4 ms]
  Range (min … max):    75.1 ms …  77.3 ms    37 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- b2sum  | wc -l
 
  Warning  Time (mean ± σ):      72.1 ms ±   2.4 ms    [User: 152.0 ms, System: 69.2 ms]
  Range (min … max):    70.1 ms …  83.0 ms    38 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l
  Time (mean ± σ):      71.4 ms ±   0.4 ms    [User: 119.3 ms, System: 41.5 ms]
  Range (min … max):    70.7 ms …  72.4 ms    40 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- b2sum  | wc -l
  Time (mean ± σ):     223.4 ms ±   1.4 ms    [User: 312.8 ms, System: 164.6 ms]
  Range (min … max):   221.3 ms … 225.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l ran
    1.01 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- b2sum  | wc -l
    1.06 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- b2sum  | wc -l
    3.13 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- b2sum  | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum -a sm3  | wc -l
  Time (mean ± σ):     143.6 ms ±   1.8 ms    [User: 340.3 ms, System: 69.4 ms]
  Range (min … max):   141.9 ms … 148.9 ms    20 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum -a sm3  | wc -l
 
  Warning  Time (mean ± σ):     134.9 ms ±   3.2 ms    [User: 338.6 ms, System: 74.2 ms]
  Range (min … max):   125.9 ms … 142.1 ms    21 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
 
  Warning: The first benchmarking run for this command was significantly slower than the rest (163.7 ms). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
  Time (mean ± σ):     159.1 ms ±   1.2 ms    [User: 303.8 ms, System: 43.4 ms]
  Range (min … max):   158.1 ms … 163.7 ms    17 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum -a sm3  | wc -l
  Time (mean ± σ):     268.9 ms ±   0.6 ms    [User: 503.5 ms, System: 173.8 ms]
  Range (min … max):   268.0 ms … 269.8 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum -a sm3  | wc -l ran
    1.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum -a sm3  | wc -l
    1.18 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
    1.99 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum -a sm3  | wc -l

-------------------------------- 16384 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha1sum  | wc -l
 
  Warning  Time (mean ± σ):     190.1 ms ±   6.0 ms    [User: 858.3 ms, System: 247.8 ms]
  Range (min … max):   186.2 ms … 205.6 ms    15 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha1sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     190.0 ms ±  10.4 ms    [User: 937.5 ms, System: 277.0 ms]
  Range (min … max):   182.6 ms … 213.5 ms    15 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l
  Time (mean ± σ):     239.3 ms ±   0.6 ms    [User: 756.3 ms, System: 198.6 ms]
  Range (min … max):   238.3 ms … 240.2 ms    12 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha1sum  | wc -l
  Time (mean ± σ):     471.8 ms ±   1.4 ms    [User: 1204.3 ms, System: 372.6 ms]
  Range (min … max):   470.4 ms … 474.4 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha1sum  | wc -l ran
    1.00 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha1sum  | wc -l
    1.26 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l
    2.48 ± 0.14 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha1sum  | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha256sum  | wc -l
 
  Warning: The first benchmarking run for this command was significantly slower than the rest (351.2 ms). This could be caused by (filesystem) caches that were not filled until after the first run.   Time (mean ± σ):     336.1 ms ±   8.2 ms    [User: 1668.5 ms, System: 257.4 ms]
  Range (min … max):   331.8 ms … 352.1 ms    10 runs
You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha256sum  | wc -l
  Time (mean ± σ):     353.2 ms ±  19.0 ms    [User: 1845.9 ms, System: 273.6 ms]
  Range (min … max):   332.6 ms … 376.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
  Time (mean ± σ):     468.4 ms ±   1.5 ms    [User: 1564.7 ms, System: 200.4 ms]
  Range (min … max):   466.7 ms … 470.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha256sum  | wc -l
  Time (mean ± σ):     552.9 ms ±   1.4 ms    [User: 2032.0 ms, System: 379.6 ms]
  Range (min … max):   551.5 ms … 556.1 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha256sum  | wc -l ran
    1.05 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha256sum  | wc -l
    1.39 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
    1.65 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha256sum  | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha512sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.  Time (mean ± σ):     254.0 ms ±  11.0 ms    [User: 1236.0 ms, System: 253.1 ms]
  Range (min … max):   246.3 ms … 278.2 ms    11 runs

 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha512sum  | wc -l
  Time (mean ± σ):     257.3 ms ±  14.0 ms    [User: 1359.5 ms, System: 278.1 ms]
  Range (min … max):   244.7 ms … 279.1 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l
  Time (mean ± σ):     332.9 ms ±   0.6 ms    [User: 1108.9 ms, System: 201.3 ms]
  Range (min … max):   331.8 ms … 334.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha512sum  | wc -l
  Time (mean ± σ):     504.9 ms ±   3.3 ms    [User: 1566.1 ms, System: 384.0 ms]
  Range (min … max):   499.7 ms … 509.4 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha512sum  | wc -l ran
    1.01 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha512sum  | wc -l
    1.31 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l
    1.99 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha512sum  | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha224sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     338.1 ms ±  12.0 ms    [User: 1669.7 ms, System: 257.6 ms]
  Range (min … max):   331.6 ms … 366.2 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha224sum  | wc -l
  Time (mean ± σ):     351.8 ms ±  16.0 ms    [User: 1846.0 ms, System: 272.4 ms]
  Range (min … max):   333.0 ms … 375.8 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
  Time (mean ± σ):     467.5 ms ±   0.6 ms    [User: 1556.8 ms, System: 205.2 ms]
  Range (min … max):   466.7 ms … 468.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha224sum  | wc -l
  Time (mean ± σ):     553.5 ms ±   3.4 ms    [User: 2020.1 ms, System: 386.0 ms]
  Range (min … max):   546.8 ms … 558.9 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha224sum  | wc -l ran
    1.04 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha224sum  | wc -l
    1.38 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
    1.64 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha224sum  | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha384sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     249.9 ms ±   8.8 ms    [User: 1196.4 ms, System: 254.3 ms]
  Range (min … max):   245.5 ms … 276.2 ms    11 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha384sum  | wc -l
 
  Warning  Time (mean ± σ):     253.9 ms ±  13.1 ms    [User: 1337.0 ms, System: 280.2 ms]
  Range (min … max):   242.8 ms … 275.6 ms    12 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
  Time (mean ± σ):     331.6 ms ±   0.8 ms    [User: 1090.8 ms, System: 205.8 ms]
  Range (min … max):   330.6 ms … 333.5 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha384sum  | wc -l
  Time (mean ± σ):     504.9 ms ±   3.5 ms    [User: 1554.8 ms, System: 385.1 ms]
  Range (min … max):   498.4 ms … 511.3 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha384sum  | wc -l ran
    1.02 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha384sum  | wc -l
    1.33 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
    2.02 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha384sum  | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- md5sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.  Time (mean ± σ):     238.2 ms ±   2.5 ms    [User: 1116.7 ms, System: 253.5 ms]
  Range (min … max):   236.5 ms … 245.8 ms    12 runs

 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- md5sum  | wc -l
 
  Warning:   Time (mean ± σ):     238.6 ms ±   7.3 ms    [User: 1166.2 ms, System: 275.5 ms]
  Range (min … max):   234.6 ms … 258.7 ms    12 runs
Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l
  Time (mean ± σ):     319.8 ms ±   0.7 ms    [User: 1034.1 ms, System: 202.0 ms]
  Range (min … max):   318.9 ms … 321.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- md5sum  | wc -l
  Time (mean ± σ):     498.3 ms ±   1.6 ms    [User: 1496.6 ms, System: 370.3 ms]
  Range (min … max):   495.6 ms … 501.6 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- md5sum  | wc -l ran
    1.00 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- md5sum  | wc -l
    1.34 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l
    2.09 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- md5sum  | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -s  | wc -l
  Time (mean ± σ):      82.6 ms ±   1.5 ms    [User: 241.0 ms, System: 240.4 ms]
  Range (min … max):    80.3 ms …  88.9 ms    34 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -s  | wc -l
  Time (mean ± σ):      76.8 ms ±   2.8 ms    [User: 262.8 ms, System: 268.7 ms]
  Range (min … max):    72.6 ms …  81.8 ms    35 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l
  Time (mean ± σ):      69.5 ms ±   0.3 ms    [User: 163.7 ms, System: 189.9 ms]
  Range (min … max):    68.9 ms …  70.0 ms    41 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -s  | wc -l
  Time (mean ± σ):     451.4 ms ±   2.5 ms    [User: 610.1 ms, System: 356.8 ms]
  Range (min … max):   449.0 ms … 456.6 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l ran
    1.11 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -s  | wc -l
    1.19 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -s  | wc -l
    6.50 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -s  | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -r  | wc -l
  Time (mean ± σ):     240.5 ms ±   1.1 ms    [User: 1138.0 ms, System: 250.2 ms]
  Range (min … max):   238.8 ms … 242.4 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -r  | wc -l
 
  Warning  Time (mean ± σ):     243.4 ms ±   8.7 ms    [User: 1183.5 ms, System: 270.9 ms]
  Range (min … max):   238.3 ms … 263.3 ms    11 runs
: The first benchmarking run for this command was significantly slower than the rest (256.3 ms). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l
  Time (mean ± σ):     324.7 ms ±   0.6 ms    [User: 1050.2 ms, System: 198.4 ms]
  Range (min … max):   323.8 ms … 325.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -r  | wc -l
  Time (mean ± σ):     499.5 ms ±   2.2 ms    [User: 1512.0 ms, System: 355.5 ms]
  Range (min … max):   496.4 ms … 504.0 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -r  | wc -l ran
    1.01 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -r  | wc -l
    1.35 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l
    2.08 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -r  | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum  | wc -l
 
    Time (mean ± σ):      73.4 ms ±   1.5 ms    [User: 181.3 ms, System: 245.9 ms]
  Range (min … max):    70.2 ms …  80.1 ms    39 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum  | wc -l
  Time (mean ± σ):      68.7 ms ±   3.1 ms    [User: 199.7 ms, System: 273.6 ms]
  Range (min … max):    64.7 ms …  77.0 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum  | wc -l
  Time (mean ± σ):      55.6 ms ±   0.3 ms    [User: 106.4 ms, System: 189.5 ms]
  Range (min … max):    55.0 ms …  57.0 ms    50 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     450.2 ms ±   2.9 ms    [User: 556.8 ms, System: 367.3 ms]
  Range (min … max):   447.8 ms … 457.4 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum  | wc -l ran
    1.23 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum  | wc -l
    1.32 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum  | wc -l
    8.09 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum  | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- b2sum  | wc -l
 
  Warning:   Time (mean ± σ):     227.9 ms ±   9.0 ms    [User: 1064.8 ms, System: 254.5 ms]
  Range (min … max):   222.5 ms … 248.0 ms    12 runs
Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- b2sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     226.4 ms ±  12.5 ms    [User: 1179.6 ms, System: 272.2 ms]
  Range (min … max):   217.7 ms … 248.6 ms    13 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l
  Time (mean ± σ):     293.1 ms ±   1.0 ms    [User: 970.0 ms, System: 195.4 ms]
  Range (min … max):   290.8 ms … 294.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- b2sum  | wc -l
  Time (mean ± σ):     490.5 ms ±   1.9 ms    [User: 1426.7 ms, System: 358.9 ms]
  Range (min … max):   487.9 ms … 493.7 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- b2sum  | wc -l ran
    1.01 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- b2sum  | wc -l
    1.29 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l
    2.17 ± 0.12 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- b2sum  | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum -a sm3  | wc -l
  Time (mean ± σ):     574.4 ms ±   3.0 ms    [User: 2965.1 ms, System: 260.0 ms]
  Range (min … max):   572.5 ms … 582.5 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum -a sm3  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     591.2 ms ±  31.1 ms    [User: 3254.0 ms, System: 282.3 ms]
  Range (min … max):   572.3 ms … 653.1 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     836.4 ms ±  11.5 ms    [User: 2844.3 ms, System: 208.6 ms]
  Range (min … max):   832.4 ms … 869.2 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum -a sm3  | wc -l
  Time (mean ± σ):     771.2 ms ±   3.7 ms    [User: 3304.7 ms, System: 388.1 ms]
  Range (min … max):   768.5 ms … 781.5 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum -a sm3  | wc -l ran
    1.03 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum -a sm3  | wc -l
    1.34 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum -a sm3  | wc -l
    1.46 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l

-------------------------------- 65536 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha1sum  | wc -l
  Time (mean ± σ):     325.1 ms ±   4.1 ms    [User: 2818.1 ms, System: 835.5 ms]
  Range (min … max):   318.8 ms … 331.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha1sum  | wc -l
  Time (mean ± σ):     306.7 ms ±  13.6 ms    [User: 4220.2 ms, System: 989.8 ms]
  Range (min … max):   285.1 ms … 325.2 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l
  Time (mean ± σ):     311.0 ms ±  19.6 ms    [User: 3813.3 ms, System: 832.7 ms]
  Range (min … max):   281.9 ms … 346.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha1sum  | wc -l
  Time (mean ± σ):      1.378 s ±  0.009 s    [User: 3.856 s, System: 1.037 s]
  Range (min … max):    1.365 s …  1.395 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha1sum  | wc -l ran
    1.01 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l
    1.06 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha1sum  | wc -l
    4.49 ± 0.20 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha1sum  | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha256sum  | wc -l
  Time (mean ± σ):     566.4 ms ±  13.2 ms    [User: 5396.3 ms, System: 866.8 ms]
  Range (min … max):   553.7 ms … 597.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha256sum  | wc -l
  Time (mean ± σ):     535.4 ms ±  21.9 ms    [User: 8454.9 ms, System: 995.7 ms]
  Range (min … max):   502.8 ms … 566.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
  Time (mean ± σ):     538.2 ms ±  18.5 ms    [User: 7906.0 ms, System: 856.2 ms]
  Range (min … max):   504.2 ms … 558.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha256sum  | wc -l
 
  Warning: The first benchmarking run for this command was significantly slower than the rest (1.494 s). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
  Time (mean ± σ):      1.446 s ±  0.018 s    [User: 6.448 s, System: 1.064 s]
  Range (min … max):    1.432 s …  1.494 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha256sum  | wc -l ran
    1.01 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
    1.06 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha256sum  | wc -l
    2.70 ± 0.12 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha256sum  | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha512sum  | wc -l
  Time (mean ± σ):     434.6 ms ±  11.0 ms    [User: 3988.0 ms, System: 864.5 ms]
  Range (min … max):   423.1 ms … 458.9 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha512sum  | wc -l
  Time (mean ± σ):     427.2 ms ±  15.4 ms    [User: 6312.5 ms, System: 987.5 ms]
  Range (min … max):   401.9 ms … 447.2 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l
  Time (mean ± σ):     418.5 ms ±  13.3 ms    [User: 5740.4 ms, System: 850.5 ms]
  Range (min … max):   386.0 ms … 437.2 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha512sum  | wc -l
  Time (mean ± σ):      1.388 s ±  0.010 s    [User: 5.021 s, System: 1.038 s]
  Range (min … max):    1.370 s …  1.404 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l ran
    1.02 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha512sum  | wc -l
    1.04 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha512sum  | wc -l
    3.32 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha512sum  | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha224sum  | wc -l
  Time (mean ± σ):     561.7 ms ±   4.1 ms    [User: 5391.8 ms, System: 860.1 ms]
  Range (min … max):   555.2 ms … 566.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha224sum  | wc -l
  Time (mean ± σ):     528.0 ms ±  18.2 ms    [User: 8434.9 ms, System: 992.8 ms]
  Range (min … max):   509.5 ms … 561.0 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
  Time (mean ± σ):     555.9 ms ±  20.4 ms    [User: 7854.9 ms, System: 851.0 ms]
  Range (min … max):   523.2 ms … 592.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha224sum  | wc -l
  Time (mean ± σ):      1.435 s ±  0.008 s    [User: 6.406 s, System: 1.072 s]
  Range (min … max):    1.422 s …  1.448 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha224sum  | wc -l ran
    1.05 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
    1.06 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha224sum  | wc -l
    2.72 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha224sum  | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha384sum  | wc -l
  Time (mean ± σ):     434.4 ms ±  16.8 ms    [User: 3957.0 ms, System: 853.6 ms]
  Range (min … max):   421.1 ms … 468.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha384sum  | wc -l
  Time (mean ± σ):     410.1 ms ±  18.3 ms    [User: 6139.2 ms, System: 994.3 ms]
  Range (min … max):   383.7 ms … 445.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
  Time (mean ± σ):     411.0 ms ±  12.7 ms    [User: 5646.3 ms, System: 848.5 ms]
  Range (min … max):   400.2 ms … 442.5 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha384sum  | wc -l
  Time (mean ± σ):      1.385 s ±  0.015 s    [User: 4.949 s, System: 1.051 s]
  Range (min … max):    1.368 s …  1.415 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha384sum  | wc -l ran
    1.00 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
    1.06 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha384sum  | wc -l
    3.38 ± 0.16 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha384sum  | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- md5sum  | wc -l
 
  Warning  Time (mean ± σ):     403.8 ms ±   7.9 ms    [User: 3595.8 ms, System: 843.2 ms]
  Range (min … max):   396.3 ms … 424.2 ms    10 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- md5sum  | wc -l
  Time (mean ± σ):     327.5 ms ±   9.9 ms    [User: 4196.2 ms, System: 1007.2 ms]
  Range (min … max):   317.9 ms … 349.1 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l
  Time (mean ± σ):     333.5 ms ±  10.9 ms    [User: 3867.5 ms, System: 861.8 ms]
  Range (min … max):   318.2 ms … 351.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- md5sum  | wc -l
  Time (mean ± σ):      1.372 s ±  0.008 s    [User: 4.710 s, System: 1.061 s]
  Range (min … max):    1.364 s …  1.385 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- md5sum  | wc -l ran
    1.02 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l
    1.23 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- md5sum  | wc -l
    4.19 ± 0.13 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- md5sum  | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -s  | wc -l
  Time (mean ± σ):     151.3 ms ±   1.7 ms    [User: 823.4 ms, System: 808.7 ms]
  Range (min … max):   148.8 ms … 154.6 ms    19 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -s  | wc -l
  Time (mean ± σ):     130.6 ms ±   2.9 ms    [User: 1049.0 ms, System: 985.1 ms]
  Range (min … max):   125.9 ms … 137.6 ms    22 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l
  Time (mean ± σ):     116.3 ms ±   4.6 ms    [User: 712.9 ms, System: 789.0 ms]
  Range (min … max):   107.1 ms … 124.3 ms    23 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -s  | wc -l
  Time (mean ± σ):      1.346 s ±  0.020 s    [User: 2.007 s, System: 0.983 s]
  Range (min … max):    1.332 s …  1.393 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l ran
    1.12 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -s  | wc -l
    1.30 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -s  | wc -l
   11.57 ± 0.49 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -s  | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -r  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.  Time (mean ± σ):     407.6 ms ±   5.9 ms    [User: 3652.4 ms, System: 826.1 ms]
  Range (min … max):   403.6 ms … 423.9 ms    10 runs

 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -r  | wc -l
  Time (mean ± σ):     328.2 ms ±   8.2 ms    [User: 4263.8 ms, System: 966.6 ms]
  Range (min … max):   319.4 ms … 344.1 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l
  Time (mean ± σ):     334.4 ms ±   5.9 ms    [User: 3926.7 ms, System: 825.4 ms]
  Range (min … max):   326.3 ms … 346.7 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -r  | wc -l
  Time (mean ± σ):      1.372 s ±  0.005 s    [User: 4.770 s, System: 1.001 s]
  Range (min … max):    1.366 s …  1.381 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -r  | wc -l ran
    1.02 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l
    1.24 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -r  | wc -l
    4.18 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -r  | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum  | wc -l
  Time (mean ± σ):     136.8 ms ±   2.3 ms    [User: 629.6 ms, System: 812.9 ms]
  Range (min … max):   132.7 ms … 141.5 ms    21 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum  | wc -l
  Time (mean ± σ):     122.7 ms ±   2.6 ms    [User: 755.6 ms, System: 971.2 ms]
  Range (min … max):   119.2 ms … 128.9 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.  Time (mean ± σ):     104.9 ms ±   3.9 ms    [User: 441.2 ms, System: 736.4 ms]
  Range (min … max):    99.2 ms … 112.9 ms    28 runs

 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum  | wc -l
  Time (mean ± σ):      1.334 s ±  0.007 s    [User: 1.818 s, System: 1.000 s]
  Range (min … max):    1.324 s …  1.345 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum  | wc -l ran
    1.17 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum  | wc -l
    1.30 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum  | wc -l
   12.72 ± 0.48 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum  | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- b2sum  | wc -l
  Time (mean ± σ):     392.8 ms ±  13.5 ms    [User: 3492.5 ms, System: 856.3 ms]
  Range (min … max):   382.1 ms … 425.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- b2sum  | wc -l
  Time (mean ± σ):     359.6 ms ±  13.5 ms    [User: 5299.5 ms, System: 976.0 ms]
  Range (min … max):   341.7 ms … 389.0 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l
  Time (mean ± σ):     368.1 ms ±   5.6 ms    [User: 4825.3 ms, System: 848.1 ms]
  Range (min … max):   359.5 ms … 375.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- b2sum  | wc -l
  Time (mean ± σ):      1.382 s ±  0.015 s    [User: 4.539 s, System: 1.031 s]
  Range (min … max):    1.357 s …  1.403 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- b2sum  | wc -l ran
    1.02 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l
    1.09 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- b2sum  | wc -l
    3.84 ± 0.15 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- b2sum  | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum -a sm3  | wc -l
  Time (mean ± σ):     942.7 ms ±  16.4 ms    [User: 9474.7 ms, System: 871.4 ms]
  Range (min … max):   927.4 ms … 978.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum -a sm3  | wc -l
  Time (mean ± σ):     922.8 ms ±  36.7 ms    [User: 15684.9 ms, System: 1089.9 ms]
  Range (min … max):   870.6 ms … 976.2 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
  Time (mean ± σ):     972.2 ms ±  18.0 ms    [User: 14985.2 ms, System: 942.4 ms]
  Range (min … max):   948.4 ms … 994.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum -a sm3  | wc -l
  Time (mean ± σ):      1.567 s ±  0.015 s    [User: 10.481 s, System: 1.075 s]
  Range (min … max):    1.548 s …  1.588 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum -a sm3  | wc -l ran
    1.02 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum -a sm3  | wc -l
    1.05 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
    1.70 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum -a sm3  | wc -l

-------------------------------- 262144 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha1sum  | wc -l
  Time (mean ± σ):      1.208 s ±  0.007 s    [User: 12.298 s, System: 3.419 s]
  Range (min … max):    1.199 s …  1.223 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha1sum  | wc -l
  Time (mean ± σ):      1.130 s ±  0.014 s    [User: 19.554 s, System: 4.059 s]
  Range (min … max):    1.116 s …  1.160 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l
  Time (mean ± σ):      1.093 s ±  0.018 s    [User: 18.394 s, System: 3.657 s]
  Range (min … max):    1.059 s …  1.116 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha1sum  | wc -l
  Time (mean ± σ):      5.221 s ±  0.032 s    [User: 16.126 s, System: 3.912 s]
  Range (min … max):    5.164 s …  5.260 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha1sum  | wc -l
    1.11 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha1sum  | wc -l
    4.78 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha1sum  | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha256sum  | wc -l
  Time (mean ± σ):      2.129 s ±  0.013 s    [User: 23.937 s, System: 3.506 s]
  Range (min … max):    2.115 s …  2.159 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha256sum  | wc -l
  Time (mean ± σ):      2.206 s ±  0.017 s    [User: 40.238 s, System: 4.074 s]
  Range (min … max):    2.178 s …  2.228 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
  Time (mean ± σ):      2.126 s ±  0.036 s    [User: 39.009 s, System: 3.648 s]
  Range (min … max):    2.081 s …  2.182 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha256sum  | wc -l
  Time (mean ± σ):      5.568 s ±  0.027 s    [User: 27.826 s, System: 4.062 s]
  Range (min … max):    5.519 s …  5.616 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l ran
    1.00 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha256sum  | wc -l
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha256sum  | wc -l
    2.62 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha256sum  | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha512sum  | wc -l
  Time (mean ± σ):      1.620 s ±  0.008 s    [User: 17.602 s, System: 3.467 s]
  Range (min … max):    1.609 s …  1.632 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha512sum  | wc -l
  Time (mean ± σ):      1.598 s ±  0.019 s    [User: 29.339 s, System: 4.018 s]
  Range (min … max):    1.582 s …  1.638 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l
  Time (mean ± σ):      1.554 s ±  0.021 s    [User: 28.101 s, System: 3.609 s]
  Range (min … max):    1.524 s …  1.580 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha512sum  | wc -l
  Time (mean ± σ):      5.401 s ±  0.039 s    [User: 21.309 s, System: 4.036 s]
  Range (min … max):    5.335 s …  5.465 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha512sum  | wc -l
    1.04 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha512sum  | wc -l
    3.48 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha512sum  | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha224sum  | wc -l
  Time (mean ± σ):      2.124 s ±  0.010 s    [User: 23.881 s, System: 3.485 s]
  Range (min … max):    2.110 s …  2.144 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha224sum  | wc -l
  Time (mean ± σ):      2.197 s ±  0.021 s    [User: 40.180 s, System: 4.133 s]
  Range (min … max):    2.164 s …  2.219 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
  Time (mean ± σ):      2.136 s ±  0.042 s    [User: 38.895 s, System: 3.720 s]
  Range (min … max):    2.088 s …  2.220 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha224sum  | wc -l
  Time (mean ± σ):      5.578 s ±  0.043 s    [User: 27.806 s, System: 4.027 s]
  Range (min … max):    5.491 s …  5.634 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha224sum  | wc -l ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
    1.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha224sum  | wc -l
    2.63 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha224sum  | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha384sum  | wc -l
  Time (mean ± σ):      1.598 s ±  0.007 s    [User: 17.283 s, System: 3.481 s]
  Range (min … max):    1.590 s …  1.609 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha384sum  | wc -l
  Time (mean ± σ):      1.582 s ±  0.018 s    [User: 28.788 s, System: 4.020 s]
  Range (min … max):    1.556 s …  1.615 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
  Time (mean ± σ):      1.526 s ±  0.032 s    [User: 27.631 s, System: 3.594 s]
  Range (min … max):    1.497 s …  1.576 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha384sum  | wc -l
  Time (mean ± σ):      5.383 s ±  0.028 s    [User: 21.070 s, System: 4.017 s]
  Range (min … max):    5.323 s …  5.432 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l ran
    1.04 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha384sum  | wc -l
    1.05 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha384sum  | wc -l
    3.53 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha384sum  | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- md5sum  | wc -l
  Time (mean ± σ):      1.491 s ±  0.004 s    [User: 15.810 s, System: 3.481 s]
  Range (min … max):    1.484 s …  1.498 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- md5sum  | wc -l
  Time (mean ± σ):      1.192 s ±  0.016 s    [User: 18.874 s, System: 4.112 s]
  Range (min … max):    1.180 s …  1.227 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l
  Time (mean ± σ):      1.148 s ±  0.012 s    [User: 17.918 s, System: 3.672 s]
  Range (min … max):    1.128 s …  1.174 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- md5sum  | wc -l
  Time (mean ± σ):      5.337 s ±  0.037 s    [User: 20.120 s, System: 3.964 s]
  Range (min … max):    5.249 s …  5.382 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l ran
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- md5sum  | wc -l
    1.30 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- md5sum  | wc -l
    4.65 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- md5sum  | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -s  | wc -l
  Time (mean ± σ):     513.6 ms ±   2.0 ms    [User: 3463.8 ms, System: 3265.0 ms]
  Range (min … max):   510.6 ms … 516.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -s  | wc -l
  Time (mean ± σ):     404.7 ms ±   5.6 ms    [User: 4422.5 ms, System: 4100.9 ms]
  Range (min … max):   400.6 ms … 419.2 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l
  Time (mean ± σ):     356.5 ms ±   4.8 ms    [User: 3281.1 ms, System: 3580.9 ms]
  Range (min … max):   348.3 ms … 365.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -s  | wc -l
  Time (mean ± σ):      4.926 s ±  0.019 s    [User: 7.739 s, System: 3.686 s]
  Range (min … max):    4.904 s …  4.971 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l ran
    1.14 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -s  | wc -l
    1.44 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -s  | wc -l
   13.82 ± 0.19 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -s  | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -r  | wc -l
  Time (mean ± σ):      1.511 s ±  0.006 s    [User: 16.159 s, System: 3.350 s]
  Range (min … max):    1.505 s …  1.522 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -r  | wc -l
  Time (mean ± σ):      1.210 s ±  0.013 s    [User: 19.125 s, System: 3.900 s]
  Range (min … max):    1.192 s …  1.230 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l
  Time (mean ± σ):      1.171 s ±  0.018 s    [User: 18.119 s, System: 3.540 s]
  Range (min … max):    1.152 s …  1.215 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -r  | wc -l
  Time (mean ± σ):      5.363 s ±  0.059 s    [User: 20.310 s, System: 3.901 s]
  Range (min … max):    5.287 s …  5.494 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -r  | wc -l
    1.29 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -r  | wc -l
    4.58 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -r  | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum  | wc -l
  Time (mean ± σ):     452.6 ms ±   3.2 ms    [User: 2594.2 ms, System: 3285.4 ms]
  Range (min … max):   449.4 ms … 460.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum  | wc -l
  Time (mean ± σ):     383.7 ms ±   3.1 ms    [User: 3086.8 ms, System: 3892.6 ms]
  Range (min … max):   378.9 ms … 389.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum  | wc -l
  Time (mean ± σ):     349.0 ms ±   4.8 ms    [User: 1872.4 ms, System: 3148.4 ms]
  Range (min … max):   342.7 ms … 357.1 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum  | wc -l
  Time (mean ± σ):      4.925 s ±  0.027 s    [User: 6.951 s, System: 3.734 s]
  Range (min … max):    4.900 s …  4.988 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum  | wc -l ran
    1.10 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum  | wc -l
    1.30 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum  | wc -l
   14.11 ± 0.21 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum  | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- b2sum  | wc -l
  Time (mean ± σ):      1.451 s ±  0.008 s    [User: 15.511 s, System: 3.372 s]
  Range (min … max):    1.442 s …  1.471 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- b2sum  | wc -l
  Time (mean ± σ):      1.364 s ±  0.013 s    [User: 24.471 s, System: 3.968 s]
  Range (min … max):    1.347 s …  1.388 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l
  Time (mean ± σ):      1.312 s ±  0.021 s    [User: 23.298 s, System: 3.588 s]
  Range (min … max):    1.281 s …  1.344 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- b2sum  | wc -l
  Time (mean ± σ):      5.335 s ±  0.065 s    [User: 19.195 s, System: 3.922 s]
  Range (min … max):    5.259 s …  5.459 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l ran
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- b2sum  | wc -l
    1.11 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- b2sum  | wc -l
    4.07 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- b2sum  | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum -a sm3  | wc -l
  Time (mean ± σ):      3.581 s ±  0.021 s    [User: 42.331 s, System: 3.589 s]
  Range (min … max):    3.561 s …  3.618 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum -a sm3  | wc -l
  Time (mean ± σ):      4.011 s ±  0.040 s    [User: 76.489 s, System: 4.706 s]
  Range (min … max):    3.959 s …  4.076 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
  Time (mean ± σ):      3.996 s ±  0.058 s    [User: 75.295 s, System: 4.285 s]
  Range (min … max):    3.899 s …  4.097 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum -a sm3  | wc -l
  Time (mean ± σ):      5.980 s ±  0.056 s    [User: 46.145 s, System: 4.181 s]
  Range (min … max):    5.898 s …  6.073 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum -a sm3  | wc -l ran
    1.12 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
    1.12 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum -a sm3  | wc -l
    1.67 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum -a sm3  | wc -l

-------------------------------- 586011 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha1sum  | wc -l
  Time (mean ± σ):      2.831 s ±  0.111 s    [User: 24.101 s, System: 6.015 s]
  Range (min … max):    2.735 s …  3.120 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha1sum  | wc -l
  Time (mean ± σ):      3.135 s ±  0.020 s    [User: 40.112 s, System: 8.496 s]
  Range (min … max):    3.106 s …  3.173 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l
  Time (mean ± σ):      3.016 s ±  0.027 s    [User: 35.687 s, System: 7.450 s]
  Range (min … max):    2.967 s …  3.053 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha1sum  | wc -l
  Time (mean ± σ):     12.469 s ±  0.187 s    [User: 35.608 s, System: 8.627 s]
  Range (min … max):   12.261 s … 12.880 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha1sum  | wc -l ran
    1.07 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha1sum  | wc -l
    1.11 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha1sum  | wc -l
    4.40 ± 0.19 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha1sum  | wc -l

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha256sum  | wc -l
  Time (mean ± σ):      5.589 s ±  0.116 s    [User: 46.861 s, System: 6.236 s]
  Range (min … max):    5.425 s …  5.855 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha256sum  | wc -l
  Time (mean ± σ):      6.227 s ±  0.051 s    [User: 81.130 s, System: 8.524 s]
  Range (min … max):    6.180 s …  6.350 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
  Time (mean ± σ):      5.965 s ±  0.077 s    [User: 72.511 s, System: 7.376 s]
  Range (min … max):    5.885 s …  6.112 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha256sum  | wc -l
  Time (mean ± σ):     12.866 s ±  0.239 s    [User: 60.308 s, System: 8.766 s]
  Range (min … max):   12.533 s … 13.252 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha256sum  | wc -l ran
    1.07 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha256sum  | wc -l
    1.11 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha256sum  | wc -l
    2.30 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha256sum  | wc -l

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha512sum  | wc -l
  Time (mean ± σ):      4.035 s ±  0.225 s    [User: 35.451 s, System: 6.169 s]
  Range (min … max):    3.791 s …  4.498 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha512sum  | wc -l
  Time (mean ± σ):      4.474 s ±  0.048 s    [User: 60.023 s, System: 8.432 s]
  Range (min … max):    4.420 s …  4.562 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l
  Time (mean ± σ):      4.300 s ±  0.051 s    [User: 54.409 s, System: 7.474 s]
  Range (min … max):    4.243 s …  4.429 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha512sum  | wc -l
  Time (mean ± σ):     12.709 s ±  0.158 s    [User: 46.583 s, System: 8.809 s]
  Range (min … max):   12.519 s … 12.958 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha512sum  | wc -l ran
    1.07 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha512sum  | wc -l
    1.11 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha512sum  | wc -l
    3.15 ± 0.18 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha512sum  | wc -l

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha224sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      5.664 s ±  0.317 s    [User: 47.097 s, System: 6.256 s]
  Range (min … max):    5.448 s …  6.399 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha224sum  | wc -l
  Time (mean ± σ):      6.222 s ±  0.052 s    [User: 80.831 s, System: 8.548 s]
  Range (min … max):    6.169 s …  6.312 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
  Time (mean ± σ):      5.972 s ±  0.051 s    [User: 72.367 s, System: 7.502 s]
  Range (min … max):    5.914 s …  6.072 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha224sum  | wc -l
  Time (mean ± σ):     12.794 s ±  0.189 s    [User: 60.203 s, System: 8.773 s]
  Range (min … max):   12.522 s … 13.040 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha224sum  | wc -l ran
    1.05 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha224sum  | wc -l
    1.10 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha224sum  | wc -l
    2.26 ± 0.13 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha224sum  | wc -l

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha384sum  | wc -l
  Time (mean ± σ):      3.948 s ±  0.081 s    [User: 34.532 s, System: 6.410 s]
  Range (min … max):    3.849 s …  4.101 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha384sum  | wc -l
  Time (mean ± σ):      4.429 s ±  0.027 s    [User: 58.898 s, System: 8.375 s]
  Range (min … max):    4.384 s …  4.471 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
  Time (mean ± σ):      4.264 s ±  0.022 s    [User: 52.875 s, System: 7.477 s]
  Range (min … max):    4.238 s …  4.294 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha384sum  | wc -l
  Time (mean ± σ):     12.697 s ±  0.170 s    [User: 46.087 s, System: 8.753 s]
  Range (min … max):   12.491 s … 12.972 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha384sum  | wc -l ran
    1.08 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha384sum  | wc -l
    1.12 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha384sum  | wc -l
    3.22 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha384sum  | wc -l

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- md5sum  | wc -l
  Time (mean ± σ):      3.572 s ±  0.054 s    [User: 27.483 s, System: 6.465 s]
  Range (min … max):    3.518 s …  3.718 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- md5sum  | wc -l
  Time (mean ± σ):      3.590 s ±  0.015 s    [User: 39.692 s, System: 8.524 s]
  Range (min … max):    3.573 s …  3.624 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l
  Time (mean ± σ):      3.562 s ±  0.028 s    [User: 36.914 s, System: 7.584 s]
  Range (min … max):    3.532 s …  3.632 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- md5sum  | wc -l
  Time (mean ± σ):     12.755 s ±  0.157 s    [User: 44.251 s, System: 8.716 s]
  Range (min … max):   12.537 s … 12.983 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- md5sum  | wc -l ran
    1.00 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- md5sum  | wc -l
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- md5sum  | wc -l
    3.58 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- md5sum  | wc -l

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -s  | wc -l
  Time (mean ± σ):     976.3 ms ±  16.6 ms    [User: 6495.0 ms, System: 5764.1 ms]
  Range (min … max):   958.0 ms … 1018.0 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -s  | wc -l
  Time (mean ± σ):     889.5 ms ±   8.1 ms    [User: 9357.8 ms, System: 8117.0 ms]
  Range (min … max):   877.1 ms … 902.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l
  Time (mean ± σ):     857.4 ms ±  18.6 ms    [User: 6812.8 ms, System: 7113.5 ms]
  Range (min … max):   838.8 ms … 900.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -s  | wc -l
  Time (mean ± σ):     11.630 s ±  0.193 s    [User: 17.475 s, System: 7.922 s]
  Range (min … max):   11.479 s … 11.942 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -s  | wc -l ran
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -s  | wc -l
    1.14 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -s  | wc -l
   13.56 ± 0.37 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -s  | wc -l

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -r  | wc -l
  Time (mean ± σ):      3.683 s ±  0.046 s    [User: 27.982 s, System: 6.029 s]
  Range (min … max):    3.629 s …  3.767 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -r  | wc -l
  Time (mean ± σ):      3.704 s ±  0.030 s    [User: 40.394 s, System: 8.161 s]
  Range (min … max):    3.657 s …  3.769 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l
  Time (mean ± σ):      3.644 s ±  0.038 s    [User: 37.334 s, System: 7.323 s]
  Range (min … max):    3.609 s …  3.742 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -r  | wc -l
  Time (mean ± σ):     12.561 s ±  0.148 s    [User: 44.490 s, System: 8.459 s]
  Range (min … max):   12.309 s … 12.875 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -r  | wc -l ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -r  | wc -l
    1.02 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -r  | wc -l
    3.45 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -r  | wc -l

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum  | wc -l
  Time (mean ± σ):     852.5 ms ±   9.5 ms    [User: 4914.4 ms, System: 5895.9 ms]
  Range (min … max):   840.1 ms … 867.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum  | wc -l
  Time (mean ± σ):     807.8 ms ±   8.4 ms    [User: 6652.0 ms, System: 7906.2 ms]
  Range (min … max):   799.3 ms … 824.0 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum  | wc -l
  Time (mean ± σ):     775.8 ms ±  13.7 ms    [User: 4062.9 ms, System: 6521.2 ms]
  Range (min … max):   761.2 ms … 803.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum  | wc -l
  Time (mean ± σ):     11.547 s ±  0.214 s    [User: 15.707 s, System: 8.026 s]
  Range (min … max):   11.308 s … 11.901 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum  | wc -l ran
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum  | wc -l
    1.10 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum  | wc -l
   14.88 ± 0.38 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum  | wc -l

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- b2sum  | wc -l
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.  Time (mean ± σ):      3.468 s ±  0.151 s    [User: 30.719 s, System: 6.005 s]
  Range (min … max):    3.383 s …  3.883 s    10 runs

 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- b2sum  | wc -l
  Time (mean ± σ):      3.816 s ±  0.035 s    [User: 50.552 s, System: 8.263 s]
  Range (min … max):    3.774 s …  3.897 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l
  Time (mean ± σ):      3.705 s ±  0.061 s    [User: 45.979 s, System: 7.434 s]
  Range (min … max):    3.646 s …  3.848 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- b2sum  | wc -l
  Time (mean ± σ):     12.651 s ±  0.210 s    [User: 42.178 s, System: 8.619 s]
  Range (min … max):   12.416 s … 13.005 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- b2sum  | wc -l ran
    1.07 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- b2sum  | wc -l
    1.10 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- b2sum  | wc -l
    3.65 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- b2sum  | wc -l

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum -a sm3  | wc -l
  Time (mean ± σ):     10.047 s ±  0.266 s    [User: 84.797 s, System: 6.608 s]
  Range (min … max):    9.711 s … 10.506 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum -a sm3  | wc -l
  Time (mean ± σ):     11.393 s ±  0.152 s    [User: 150.736 s, System: 9.383 s]
  Range (min … max):   11.256 s … 11.696 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
  Time (mean ± σ):     10.945 s ±  0.101 s    [User: 135.176 s, System: 8.221 s]
  Range (min … max):   10.817 s … 11.141 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum -a sm3  | wc -l
  Time (mean ± σ):     14.695 s ±  0.208 s    [User: 100.270 s, System: 9.232 s]
  Range (min … max):   14.544 s … 15.239 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum -a sm3  | wc -l ran
    1.09 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum -a sm3  | wc -l
    1.13 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum -a sm3  | wc -l
    1.46 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum -a sm3  | wc -l

-----------------------------------------------------
-------------------- "min" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0727909484    0.0721305814    0.0788373894    0.1968212684    0.1171386160    0.1159533860    0.1449541600    0.2619903380    0.0906889958    0.0901670718    0.1072778708    0.2242875508    0.1172559698    0.1161459418    0.1454880178    0.2613686278    0.0906457169    0.0900877089    0.1064139149    0.2243681519        0.0884572677    0.0881378137    0.1018495227    0.2202130767    0.0381572195    0.0372513105    0.0293099755    0.1724412355    0.0895230656    0.0885486016    0.1030344656    0.2213767686    0.0354696130    0.0355605850    0.0247808760    0.1735190540    0.0830498856    0.0815457496    0.09529312160.2134504326    0.1883353272    0.1864050522    0.2509072732    0.3632249692
4096    0.0664278308    0.0619047708    0.0594187838    0.2224892818    0.0945181123    0.0904343873    0.0978786903    0.2286592093    0.0803079665    0.0750516315    0.0780585735    0.2208045055    0.0959522167    0.0902175497    0.0975216177    0.2282765767    0.0792621711    0.0745439521    0.0764894291    0.2216300971        0.0765142401    0.0694213191    0.0723503141    0.2218384581    0.0445384770    0.0417860690    0.0310565350    0.2228472540    0.0773433519    0.0703813399    0.0724675049    0.2220516529    0.0418406962    0.0396435562    0.0274356872    0.2233059332    0.0751146043    0.0700748893    0.07069352530.2213064253    0.1419228557    0.1258886447    0.1580760217    0.2679766787
16384   0.1862208035    0.1826028735    0.2383253415    0.4704411405    0.3317706432    0.3326049772    0.4667398222    0.5514548212    0.2463284319    0.2447381729    0.3317904969    0.4996815369    0.3315553023    0.3329955413    0.4667180603    0.5467947323    0.2454518505    0.2428015645    0.3306483425    0.4984316085        0.2365388852    0.2345669132    0.3188788222    0.4956168022    0.0802972729    0.0726098199    0.0688817879    0.4490241069    0.2387821979    0.2382739629    0.3238040599    0.4963946989    0.0702216043    0.0647001893    0.0549914563    0.4477794403    0.2224535686    0.2177290366    0.29075243760.4878648416    0.5724779965    0.5722535195    0.8324217935    0.7684606835
65536   0.3187960278    0.2851471278    0.2818610638    1.3649009688    0.5537100482    0.5027538112    0.5042499752    1.4316240652    0.4230509262    0.4019342902    0.3860287962    1.3696484032    0.5551972451    0.5094647931    0.5231756221    1.4224538051    0.4211379927    0.3836750147    0.4001875667    1.3677049177        0.3962799619    0.3178807229    0.3182379669    1.3637583708    0.1488329597    0.1258972077    0.1071216587    1.3315278827    0.4036056487    0.3193895357    0.3263087967    1.3663025787    0.1327068403    0.1192064683    0.0991656413    1.3240214163    0.3821419233    0.3417272233    0.35951751131.3565276733    0.9274433999    0.8705739929    0.9484215629    1.5483617599
262144  1.1986085349    1.1161550779    1.0592060099    5.1643642549    2.1151067865    2.1779027655    2.0814299745    5.5193368345    1.6089549863    1.5816164883    1.5239542503    5.3350921763    2.1095144199    2.1643147129    2.0884275799    5.4914442969    1.5898197282    1.5555087182    1.4969365512    5.3225120792        1.4842651126    1.1797516196    1.1284552076    5.2490673976    0.5105635407    0.4005653827    0.3483275007    4.9035541277    1.5045124681    1.1923900651    1.1521458081    5.2869831351    0.4494298797    0.3789309407    0.3427083557    4.9003907957    1.4416922201    1.3470422441    1.28096069215.2591042651    3.5609809289    3.9590204259    3.8994818158    5.8983832359
586011  2.7346742671    3.1060590531    2.9671637241    12.261472287    5.4249901265    6.1801884685    5.8847116955    12.533251697    3.7912070866    4.4196076566    4.2428958396    12.518635036    5.4478799615    6.1687084205    5.9140621735    12.522217938    3.8491270784    4.3844598904    4.2380369764    12.491213891        3.5180099520    3.5729332690    3.5322063150    12.536524849    0.9580296342    0.8771306292    0.8388237102    11.478736156    3.6289536652    3.6567931602    3.6086293682    12.309411787    0.8401106904    0.7993411524    0.7611932124    11.308393780    3.3829161752    3.7743560782    3.645657962212.416272916    9.7106376856    11.255945724    10.816532859    14.544210195

-----------------------------------------------------
-------------------- "mean" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0731612638    0.0726775423    0.0794611338    0.1982461964    0.1179459683    0.1169939798    0.1461393984    0.2631867201    0.0913956325    0.0908050620    0.1080361316    0.2256388234    0.1189647631    0.1172883690    0.1463416076    0.2632299072    0.0913475549    0.0906143978    0.1069994374    0.2250033949        0.0891808800    0.0886807352    0.1025739297    0.2212802584    0.0384947728    0.0378473343    0.0297792463    0.1743976518    0.0903447205    0.0892292183    0.1036825088    0.2223534273    0.0358901856    0.0359324370    0.0253891857    0.1751609853    0.0838256500    0.0825893029    0.09597486740.2143355036    0.1888712932    0.1874776793    0.2526857401    0.3646074396
4096    0.0669916416    0.0637366031    0.0598828663    0.2240592736    0.0971082032    0.0920376487    0.0986222931    0.2301232559    0.0811963251    0.0767119792    0.0786005164    0.2234853501    0.0975016557    0.0913132715    0.0982159924    0.2299287054    0.0803036616    0.0757839431    0.0772228378    0.2248417943        0.0771956861    0.0733661565    0.0728506643    0.2237301428    0.0449459675    0.0427992029    0.0314801320    0.2241154001    0.0779623579    0.0741405119    0.0731123631    0.2237509811    0.0425363665    0.0403096503    0.0279443549    0.2250169120    0.0759264979    0.0720735154    0.07138662980.2234462306    0.1436138770    0.1348584169    0.1591227407    0.2688837688
16384   0.1901449885    0.1899590740    0.2392614786    0.4718108749    0.3361066683    0.3532484553    0.4683609859    0.5529047832    0.2539669912    0.2572522605    0.3328694221    0.5048905679    0.3380836664    0.3518454964    0.4674501604    0.5534842011    0.2499058557    0.2538653119    0.3316386063    0.5049208596        0.2382456489    0.2385695730    0.3198088906    0.4982601248    0.0826194524    0.0767522962    0.0694583251    0.4513592053    0.2404648623    0.2433701059    0.3246636909    0.4994838530    0.0733604840    0.0686502414    0.0556333861    0.4502042010    0.2278993322    0.2263647458    0.29311327530.4904553450    0.5743766226    0.5911563319    0.8363826869    0.7712030518
65536   0.3250722407    0.3067035100    0.3109897361    1.3784741499    0.5664363809    0.5353927894    0.5382303376    1.4461349870    0.4345544078    0.4271914829    0.4185044538    1.3880456847    0.5616820015    0.5279523758    0.5559479555    1.4352032801    0.4343584876    0.4101149270    0.4110238033    1.3847170408        0.4038330988    0.3275310031    0.3334954350    1.3723352705    0.1513145127    0.1305986011    0.1163486814    1.3458414492    0.4076167815    0.3281906760    0.3344449610    1.3717910379    0.1367991905    0.1227366270    0.1048764788    1.3343968874    0.3928224392    0.3596149893    0.36811805731.3820127965    0.9427080607    0.9227854010    0.9721543789    1.5669939696
262144  1.2081390100    1.1298657723    1.0927677203    5.2213775475    2.1288093727    2.2055645519    2.1260736941    5.5675015318    1.6204445413    1.5979295691    1.5540226900    5.4010445192    2.1236036511    2.1972564096    2.1363121162    5.5780732732    1.5980579672    1.5816143133    1.5262387993    5.3828930822        1.4905172053    1.1924378260    1.1482506529    5.3374165641    0.5135596115    0.4047147536    0.3565196903    4.9259558845    1.5110264779    1.2097741664    1.1709841545    5.3628440157    0.4525677526    0.3836583552    0.3490155784    4.9254489633    1.4513410377    1.3642071861    1.31158845345.3349616940    3.5812350354    4.0112135359    3.9960698332    5.9799603511
586011  2.8309601974    3.1348596751    3.0158309621    12.468960908    5.5891415393    6.2265494598    5.9648955419    12.866310598    4.0353432110    4.4740216657    4.3003445363    12.709176534    5.6642231494    6.2218139375    5.9718326184    12.794395108    3.9482545919    4.4287364359    4.2642353406    12.696535459        3.5724025772    3.589618096,    3.5616742688    12.755032532    0.9763332829    0.8894793827    0.8574476735    11.630226901    3.6829799327    3.7039768774    3.6439649553    12.561477830    0.8524876334    0.8077794064    0.7758177883    11.546945851    3.4682437692    3.8159986363    3.705010661112.650904000    10.046526181    11.393019556    10.945107920    14.694500090

-----------------------------------------------------
-------------------- "max" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0760476584    0.0737681634    0.0806849614    0.1995197984    0.1194877470    0.1184617810    0.1486494490    0.2641019180    0.0921387288    0.0918679048    0.1113751308    0.2265730768    0.1401585258    0.1210485158    0.1477412398    0.2690226948    0.0947214139    0.0912970579    0.1079848179    0.2265016839        0.0899838737    0.0906717517    0.1032544807    0.2242750587    0.0389707545    0.0392544135    0.0307206865    0.1754082875    0.0911583476    0.0903233886    0.1045590696    0.2240482926    0.0372887680    0.0366472020    0.0262465340    0.1767099280    0.0849030016    0.0834565066    0.09672851760.2156681956    0.1900059202    0.1897293372    0.2603017232    0.3654200262
4096    0.0688744268    0.0665516368    0.0611364448    0.2262604598    0.1000913953    0.0964913073    0.1005155973    0.2314375643    0.0836850615    0.0876732145    0.0795434015    0.2274945615    0.1091288327    0.0957023797    0.1022991857    0.2314924157    0.0825457041    0.0794038651    0.0783194041    0.2279926831        0.0794845441    0.0767752691    0.0737272791    0.2257000161    0.0458010330    0.0452560430    0.0323107900    0.2261336620    0.0786177469    0.0771257339    0.0741206629    0.2283189669    0.0447323492    0.0422621342    0.0284558432    0.2299050222    0.0772731143    0.0829738483    0.07238642930.2258507563    0.1488935127    0.1420771427    0.1636647177    0.2698393627
16384   0.2055826125    0.2135133065    0.2401950935    0.4744330085    0.3520572142    0.3769366242    0.4707994472    0.5561193082    0.2781575819    0.2791336109    0.3339667419    0.5093886809    0.3662221633    0.3757585743    0.4685977323    0.5588840073    0.2762263495    0.2755762885    0.3335153775    0.5112762985        0.2458321702    0.2587037242    0.3210204052    0.5016055422    0.0889263809    0.0817643879    0.0699552049    0.4566210059    0.2423692509    0.2633059999    0.3255731939    0.5039690879    0.0801398783    0.0769542713    0.0570140973    0.4574073363    0.2480285086    0.2485762086    0.29438861460.4936684116    0.5825396185    0.6531286625    0.8691577995    0.7814518945
65536   0.3317570798    0.3252092458    0.3463856068    1.3950733588    0.5975656702    0.5667037902    0.5585628142    1.4942176712    0.4588619212    0.4472185262    0.4371517312    1.4042282252    0.5660623521    0.5609997551    0.5919926151    1.4483740141    0.4685940597    0.4459142537    0.4425035717    1.4148394347        0.4241932969    0.3491311719    0.3509632629    1.3848163419    0.1546433987    0.1375929877    0.1243415007    1.3929050837    0.4239116427    0.3440933607    0.3466707907    1.3809329957    0.1414820283    0.1288732653    0.1129083123    1.3452479493    0.4251226153    0.3889740843    0.37579035031.4028473543    0.9785992309    0.9762017899    0.9944347039    1.5884410059
262144  1.2226214799    1.1601665939    1.1162426429    5.2597221069    2.1594649445    2.2279430935    2.1816119015    5.6161921965    1.6315689543    1.6383581503    1.5800233063    5.4645045693    2.1436419549    2.2190602679    2.2201350979    5.6343041149    1.6094753632    1.6145746142    1.5763812852    5.4321994572        1.4977578436    1.2269395266    1.1735229406    5.3815366026    0.5167759217    0.4191515777    0.3652888257    4.9711165757    1.5218528951    1.2299429561    1.2150218221    5.4942501031    0.4608337337    0.3896442337    0.3570792177    4.9884615727    1.4710407451    1.3881612701    1.34434484415.4587825551    3.6178414339    4.0756793219    4.0969149489    6.0730372579
586011  3.1198912701    3.1726572201    3.0526272181    12.879689687    5.8554006445    6.3498555005    6.1124086515    13.252264258    4.4975039066    4.5616362496    4.4291355626    12.957787755    6.3987892845    6.3123807515    6.0723346305    13.039546450    4.1006451164    4.4707940674    4.2938163734    12.972259503        3.71777238,     3.6243981560    3.632024695,    12.982604108    1.0180063802    0.9024122252    0.8999820422    11.942148275    3.7673521262    3.7691865212    3.7424598342    12.875188246    0.8676349954    0.8239882454    0.8032585684    11.900856472    3.8833645112    3.8971317812    3.848165951213.005312507    10.505569993    11.695859164    11.140798582    15.238838563


||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0731612638    0.0726775423    0.0794611338    0.1982461964    forkrun is 9.333% faster than xargs (1.0933x)   forkrun is 172.7% faster than parallel (2.7277x)
sha256sum       0.1179459683    0.1169939798    0.1461393984    0.2631867201    forkrun is 24.91% faster than xargs (1.2491x)   forkrun is 124.9% faster than parallel (2.2495x)
sha512sum       0.0913956325    0.0908050620    0.1080361316    0.2256388234    forkrun is 18.97% faster than xargs (1.1897x)   forkrun is 148.4% faster than parallel (2.4848x)
sha224sum       0.1189647631    0.1172883690    0.1463416076    0.2632299072    forkrun is 24.77% faster than xargs (1.2477x)   forkrun is 124.4% faster than parallel (2.2442x)
sha384sum       0.0913475549    0.0906143978    0.1069994374    0.2250033949    forkrun is 18.08% faster than xargs (1.1808x)   forkrun is 148.3% faster than parallel (2.4830x)
md5sum          0.0891808800    0.0886807352    0.1025739297    0.2212802584    forkrun is 15.66% faster than xargs (1.1566x)   forkrun is 149.5% faster than parallel (2.4952x)
sum -s          0.0384947728    0.0378473343    0.0297792463    0.1743976518    xargs is 27.09% faster than forkrun (1.2709x)   forkrun is 360.7% faster than parallel (4.6079x)
sum -r          0.0903447205    0.0892292183    0.1036825088    0.2223534273    forkrun is 16.19% faster than xargs (1.1619x)   forkrun is 149.1% faster than parallel (2.4919x)
cksum           0.0358901856    0.0359324370    0.0253891857    0.1751609853    xargs is 41.36% faster than forkrun (1.4136x)   forkrun is 388.0% faster than parallel (4.8804x)
b2sum           0.0838256500    0.0825893029    0.0959748674    0.2143355036    forkrun is 16.20% faster than xargs (1.1620x)   forkrun is 159.5% faster than parallel (2.5951x)
cksum -a sm3    0.1888712932    0.1874776793    0.2526857401    0.3646074396    forkrun is 34.78% faster than xargs (1.3478x)   forkrun is 94.48% faster than parallel (1.9448x)

OVERALL         1.0194226852    1.0101360586    1.1970631873    2.5474403085    forkrun is 18.50% faster than xargs (1.1850x)   forkrun is 152.1% faster than parallel (2.5218x)




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0669916416    0.0637366031    0.0598828663    0.2240592736    xargs is 6.435% faster than forkrun (1.0643x)   forkrun is 251.5% faster than parallel (3.5153x)
sha256sum       0.0971082032    0.0920376487    0.0986222931    0.2301232559    forkrun is 1.559% faster than xargs (1.0155x)   forkrun is 136.9% faster than parallel (2.3697x)
sha512sum       0.0811963251    0.0767119792    0.0786005164    0.2234853501    forkrun is 2.461% faster than xargs (1.0246x)   forkrun is 191.3% faster than parallel (2.9133x)
sha224sum       0.0975016557    0.0913132715    0.0982159924    0.2299287054    forkrun is 7.559% faster than xargs (1.0755x)   forkrun is 151.8% faster than parallel (2.5180x)
sha384sum       0.0803036616    0.0757839431    0.0772228378    0.2248417943    forkrun is 1.898% faster than xargs (1.0189x)   forkrun is 196.6% faster than parallel (2.9668x)
md5sum          0.0771956861    0.0733661565    0.0728506643    0.2237301428    xargs is .7076% faster than forkrun (1.0070x)   forkrun is 204.9% faster than parallel (3.0495x)
sum -s          0.0449459675    0.0427992029    0.0314801320    0.2241154001    xargs is 35.95% faster than forkrun (1.3595x)   forkrun is 423.6% faster than parallel (5.2364x)
sum -r          0.0779623579    0.0741405119    0.0731123631    0.2237509811    xargs is 1.406% faster than forkrun (1.0140x)   forkrun is 201.7% faster than parallel (3.0179x)
cksum           0.0425363665    0.0403096503    0.0279443549    0.2250169120    xargs is 52.21% faster than forkrun (1.5221x)   forkrun is 428.9% faster than parallel (5.2899x)
b2sum           0.0759264979    0.0720735154    0.0713866298    0.2234462306    xargs is .9622% faster than forkrun (1.0096x)   forkrun is 210.0% faster than parallel (3.1002x)
cksum -a sm3    0.1436138770    0.1348584169    0.1591227407    0.2688837688    forkrun is 10.79% faster than xargs (1.1079x)   forkrun is 87.22% faster than parallel (1.8722x)

OVERALL         .88528224077    .83713090009    .84844139134    2.5213818152    forkrun is 1.351% faster than xargs (1.0135x)   forkrun is 201.1% faster than parallel (3.0119x)




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.1901449885    0.1899590740    0.2392614786    0.4718108749    forkrun is 25.95% faster than xargs (1.2595x)   forkrun is 148.3% faster than parallel (2.4837x)
sha256sum       0.3361066683    0.3532484553    0.4683609859    0.5529047832    forkrun is 39.34% faster than xargs (1.3934x)   forkrun is 64.50% faster than parallel (1.6450x)
sha512sum       0.2539669912    0.2572522605    0.3328694221    0.5048905679    forkrun is 29.39% faster than xargs (1.2939x)   forkrun is 96.26% faster than parallel (1.9626x)
sha224sum       0.3380836664    0.3518454964    0.4674501604    0.5534842011    forkrun is 38.26% faster than xargs (1.3826x)   forkrun is 63.71% faster than parallel (1.6371x)
sha384sum       0.2499058557    0.2538653119    0.3316386063    0.5049208596    forkrun is 32.70% faster than xargs (1.3270x)   forkrun is 102.0% faster than parallel (2.0204x)
md5sum          0.2382456489    0.2385695730    0.3198088906    0.4982601248    forkrun is 34.23% faster than xargs (1.3423x)   forkrun is 109.1% faster than parallel (2.0913x)
sum -s          0.0826194524    0.0767522962    0.0694583251    0.4513592053    xargs is 10.50% faster than forkrun (1.1050x)   forkrun is 488.0% faster than parallel (5.8807x)
sum -r          0.2404648623    0.2433701059    0.3246636909    0.4994838530    forkrun is 33.40% faster than xargs (1.3340x)   forkrun is 105.2% faster than parallel (2.0523x)
cksum           0.0733604840    0.0686502414    0.0556333861    0.4502042010    xargs is 23.39% faster than forkrun (1.2339x)   forkrun is 555.7% faster than parallel (6.5579x)
b2sum           0.2278993322    0.2263647458    0.2931132753    0.4904553450    forkrun is 28.61% faster than xargs (1.2861x)   forkrun is 115.2% faster than parallel (2.1520x)
cksum -a sm3    0.5743766226    0.5911563319    0.8363826869    0.7712030518    forkrun is 45.61% faster than xargs (1.4561x)   forkrun is 34.26% faster than parallel (1.3426x)

OVERALL         2.8051745729    2.8510338927    3.7386409087    5.7489770681    forkrun is 33.27% faster than xargs (1.3327x)   forkrun is 104.9% faster than parallel (2.0494x)




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.3250722407    0.3067035100    0.3109897361    1.3784741499    forkrun is 1.397% faster than xargs (1.0139x)   forkrun is 349.4% faster than parallel (4.4944x)
sha256sum       0.5664363809    0.5353927894    0.5382303376    1.4461349870    forkrun is .5299% faster than xargs (1.0052x)   forkrun is 170.1% faster than parallel (2.7010x)
sha512sum       0.4345544078    0.4271914829    0.4185044538    1.3880456847    xargs is 2.075% faster than forkrun (1.0207x)   forkrun is 224.9% faster than parallel (3.2492x)
sha224sum       0.5616820015    0.5279523758    0.5559479555    1.4352032801    xargs is 1.031% faster than forkrun (1.0103x)   forkrun is 155.5% faster than parallel (2.5551x)
sha384sum       0.4343584876    0.4101149270    0.4110238033    1.3847170408    forkrun is .2216% faster than xargs (1.0022x)   forkrun is 237.6% faster than parallel (3.3764x)
md5sum          0.4038330988    0.3275310031    0.3334954350    1.3723352705    xargs is 21.09% faster than forkrun (1.2109x)   forkrun is 239.8% faster than parallel (3.3982x)
sum -s          0.1513145127    0.1305986011    0.1163486814    1.3458414492    xargs is 12.24% faster than forkrun (1.1224x)   forkrun is 930.5% faster than parallel (10.305x)
sum -r          0.4076167815    0.3281906760    0.3344449610    1.3717910379    forkrun is 1.905% faster than xargs (1.0190x)   forkrun is 317.9% faster than parallel (4.1798x)
cksum           0.1367991905    0.1227366270    0.1048764788    1.3343968874    xargs is 17.02% faster than forkrun (1.1702x)   forkrun is 987.2% faster than parallel (10.872x)
b2sum           0.3928224392    0.3596149893    0.3681180573    1.3820127965    forkrun is 2.364% faster than xargs (1.0236x)   forkrun is 284.3% faster than parallel (3.8430x)
cksum -a sm3    0.9427080607    0.9227854010    0.9721543789    1.5669939696    forkrun is 5.349% faster than xargs (1.0534x)   forkrun is 69.81% faster than parallel (1.6981x)

OVERALL         4.7571976023    4.3988123831    4.4641342792    15.405946554    forkrun is 1.484% faster than xargs (1.0148x)   forkrun is 250.2% faster than parallel (3.5022x)




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         1.2081390100    1.1298657723    1.0927677203    5.2213775475    xargs is 3.394% faster than forkrun (1.0339x)   forkrun is 362.1% faster than parallel (4.6212x)
sha256sum       2.1288093727    2.2055645519    2.1260736941    5.5675015318    xargs is .1286% faster than forkrun (1.0012x)   forkrun is 161.5% faster than parallel (2.6153x)
sha512sum       1.6204445413    1.5979295691    1.5540226900    5.4010445192    xargs is 2.825% faster than forkrun (1.0282x)   forkrun is 238.0% faster than parallel (3.3800x)
sha224sum       2.1236036511    2.1972564096    2.1363121162    5.5780732732    forkrun is .5984% faster than xargs (1.0059x)   forkrun is 162.6% faster than parallel (2.6267x)
sha384sum       1.5980579672    1.5816143133    1.5262387993    5.3828930822    xargs is 4.705% faster than forkrun (1.0470x)   forkrun is 236.8% faster than parallel (3.3683x)
md5sum          1.4905172053    1.1924378260    1.1482506529    5.3374165641    xargs is 3.848% faster than forkrun (1.0384x)   forkrun is 347.6% faster than parallel (4.4760x)
sum -s          0.5135596115    0.4047147536    0.3565196903    4.9259558845    xargs is 13.51% faster than forkrun (1.1351x)   forkrun is 1117.% faster than parallel (12.171x)
sum -r          1.5110264779    1.2097741664    1.1709841545    5.3628440157    xargs is 3.312% faster than forkrun (1.0331x)   forkrun is 343.2% faster than parallel (4.4329x)
cksum           0.4525677526    0.3836583552    0.3490155784    4.9254489633    xargs is 29.66% faster than forkrun (1.2966x)   forkrun is 988.3% faster than parallel (10.883x)
b2sum           1.4513410377    1.3642071861    1.3115884534    5.3349616940    xargs is 10.65% faster than forkrun (1.1065x)   forkrun is 267.5% faster than parallel (3.6758x)
cksum -a sm3    3.5812350354    4.0112135359    3.9960698332    5.9799603511    forkrun is 11.58% faster than xargs (1.1158x)   forkrun is 66.98% faster than parallel (1.6698x)

OVERALL         17.679301663    17.278236439    16.767843383    59.017477427    xargs is 5.435% faster than forkrun (1.0543x)   forkrun is 233.8% faster than parallel (3.3382x)




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         2.8309601974    3.1348596751    3.0158309621    12.468960908    forkrun is 6.530% faster than xargs (1.0653x)   forkrun is 340.4% faster than parallel (4.4044x)
sha256sum       5.5891415393    6.2265494598    5.9648955419    12.866310598    forkrun is 6.722% faster than xargs (1.0672x)   forkrun is 130.2% faster than parallel (2.3020x)
sha512sum       4.0353432110    4.4740216657    4.3003445363    12.709176534    forkrun is 6.567% faster than xargs (1.0656x)   forkrun is 214.9% faster than parallel (3.1494x)
sha224sum       5.6642231494    6.2218139375    5.9718326184    12.794395108    forkrun is 5.430% faster than xargs (1.0543x)   forkrun is 125.8% faster than parallel (2.2588x)
sha384sum       3.9482545919    4.4287364359    4.2642353406    12.696535459    forkrun is 8.003% faster than xargs (1.0800x)   forkrun is 221.5% faster than parallel (3.2157x)
md5sum          3.5724025772    3.589618096     3.5616742688    12.755032532    xargs is .7845% faster than forkrun (1.0078x)   forkrun is 255.3% faster than parallel (3.5533x)
sum -s          0.9763332829    0.8894793827    0.8574476735    11.630226901    xargs is 3.735% faster than forkrun (1.0373x)   forkrun is 1207.% faster than parallel (13.075x)
sum -r          3.6829799327    3.7039768774    3.6439649553    12.561477830    xargs is 1.070% faster than forkrun (1.0107x)   forkrun is 241.0% faster than parallel (3.4106x)
cksum           0.8524876334    0.8077794064    0.7758177883    11.546945851    xargs is 9.882% faster than forkrun (1.0988x)   forkrun is 1254.% faster than parallel (13.545x)
b2sum           3.4682437692    3.8159986363    3.7050106611    12.650904000    forkrun is 6.826% faster than xargs (1.0682x)   forkrun is 264.7% faster than parallel (3.6476x)
cksum -a sm3    10.046526181    11.393019556    10.945107920    14.694500090    forkrun is 8.944% faster than xargs (1.0894x)   forkrun is 46.26% faster than parallel (1.4626x)

OVERALL         44.666896065    48.685853129    47.006162267    139.37446581    forkrun is 5.237% faster than xargs (1.0523x)   forkrun is 212.0% faster than parallel (3.1203x)


-------------------------------- 1024 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.7 ms ±   0.1 ms    [User: 27.5 ms, System: 27.2 ms]
  Range (min … max):    27.4 ms …  28.2 ms    95 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.8 ms ±   0.1 ms    [User: 30.0 ms, System: 31.4 ms]
  Range (min … max):    27.5 ms …  28.2 ms    95 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.5 ms, System: 3.1 ms]
  Range (min … max):     7.0 ms …   7.6 ms    284 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.6 ms ±   1.1 ms    [User: 97.3 ms, System: 63.6 ms]
  Range (min … max):   127.5 ms … 133.1 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    3.90 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    3.91 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   18.24 ± 0.30 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.7 ms ±   0.1 ms    [User: 28.0 ms, System: 26.6 ms]
  Range (min … max):    27.4 ms …  28.1 ms    96 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.9 ms ±   0.2 ms    [User: 29.8 ms, System: 31.8 ms]
  Range (min … max):    27.5 ms …  28.7 ms    96 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.5 ms, System: 3.2 ms]
  Range (min … max):     7.0 ms …   7.9 ms    286 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.6 ms ±   0.5 ms    [User: 95.1 ms, System: 66.2 ms]
  Range (min … max):   128.7 ms … 130.9 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    3.90 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    3.92 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   18.23 ± 0.23 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.7 ms ±   0.1 ms    [User: 27.9 ms, System: 26.8 ms]
  Range (min … max):    27.3 ms …  28.1 ms    95 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.8 ms ±   0.1 ms    [User: 30.0 ms, System: 31.6 ms]
  Range (min … max):    27.5 ms …  28.4 ms    96 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.4 ms, System: 3.2 ms]
  Range (min … max):     7.0 ms …   7.7 ms    286 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.6 ms ±   1.3 ms    [User: 97.0 ms, System: 64.0 ms]
  Range (min … max):   128.0 ms … 134.4 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    3.90 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    3.92 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   18.26 ± 0.28 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.7 ms ±   0.1 ms    [User: 27.8 ms, System: 26.9 ms]
  Range (min … max):    27.4 ms …  28.2 ms    97 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.8 ms ±   0.2 ms    [User: 30.3 ms, System: 31.3 ms]
  Range (min … max):    27.5 ms …  28.3 ms    96 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.5 ms, System: 3.2 ms]
  Range (min … max):     6.9 ms …   8.1 ms    286 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.2 ms ±   0.5 ms    [User: 96.5 ms, System: 64.4 ms]
  Range (min … max):   128.3 ms … 130.2 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    3.90 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    3.91 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   18.16 ± 0.31 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.7 ms ±   0.1 ms    [User: 27.8 ms, System: 26.9 ms]
  Range (min … max):    27.3 ms …  28.1 ms    96 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.8 ms ±   0.1 ms    [User: 30.4 ms, System: 31.2 ms]
  Range (min … max):    27.3 ms …  28.2 ms    95 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.7 ms, System: 3.0 ms]
  Range (min … max):     6.9 ms …   8.0 ms    284 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.4 ms ±   0.5 ms    [User: 95.7 ms, System: 65.1 ms]
  Range (min … max):   128.4 ms … 130.2 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    3.90 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    3.91 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   18.21 ± 0.33 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.7 ms ±   0.2 ms    [User: 27.7 ms, System: 27.0 ms]
  Range (min … max):    27.4 ms …  28.9 ms    95 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.8 ms ±   0.1 ms    [User: 30.2 ms, System: 31.3 ms]
  Range (min … max):    27.5 ms …  28.2 ms    95 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.5 ms, System: 3.1 ms]
  Range (min … max):     6.9 ms …   8.1 ms    286 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.6 ms ±   0.8 ms    [User: 95.8 ms, System: 65.4 ms]
  Range (min … max):   128.8 ms … 131.9 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    3.91 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    3.92 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   18.27 ± 0.31 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.1 ms ±   0.2 ms    [User: 28.7 ms, System: 25.5 ms]
  Range (min … max):    26.8 ms …  27.5 ms    98 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.0 ms ±   0.2 ms    [User: 29.3 ms, System: 26.5 ms]
  Range (min … max):    26.6 ms …  28.0 ms    98 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       6.7 ms ±   0.1 ms    [User: 4.4 ms, System: 2.8 ms]
  Range (min … max):     6.6 ms …   7.7 ms    298 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.2 ms ±   0.8 ms    [User: 94.8 ms, System: 65.2 ms]
  Range (min … max):   127.4 ms … 130.6 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    4.01 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    4.03 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   19.19 ± 0.31 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.1 ms ±   0.2 ms    [User: 28.8 ms, System: 25.5 ms]
  Range (min … max):    26.7 ms …  27.7 ms    98 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.0 ms ±   0.2 ms    [User: 29.7 ms, System: 26.4 ms]
  Range (min … max):    26.7 ms …  27.9 ms    98 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       6.7 ms ±   0.1 ms    [User: 4.5 ms, System: 2.7 ms]
  Range (min … max):     6.6 ms …   7.5 ms    297 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.6 ms ±   0.7 ms    [User: 96.9 ms, System: 63.8 ms]
  Range (min … max):   128.2 ms … 130.9 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    4.02 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    4.04 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   19.27 ± 0.35 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.7 ms ±   0.2 ms    [User: 27.8 ms, System: 27.0 ms]
  Range (min … max):    27.3 ms …  28.3 ms    96 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.8 ms ±   0.2 ms    [User: 30.3 ms, System: 31.4 ms]
  Range (min … max):    27.5 ms …  28.4 ms    96 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.4 ms, System: 3.2 ms]
  Range (min … max):     6.9 ms …   7.8 ms    285 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.9 ms ±   0.5 ms    [User: 96.6 ms, System: 64.9 ms]
  Range (min … max):   128.8 ms … 130.6 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    3.90 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    3.91 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   18.25 ± 0.28 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.2 ms ±   0.2 ms    [User: 28.9 ms, System: 26.0 ms]
  Range (min … max):    26.8 ms …  27.5 ms    97 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.0 ms ±   0.2 ms    [User: 29.3 ms, System: 26.8 ms]
  Range (min … max):    26.6 ms …  27.6 ms    98 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       6.7 ms ±   0.1 ms    [User: 4.4 ms, System: 2.8 ms]
  Range (min … max):     6.6 ms …   7.5 ms    293 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.4 ms ±   0.6 ms    [User: 96.2 ms, System: 64.4 ms]
  Range (min … max):   128.3 ms … 130.7 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    4.03 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    4.06 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   19.31 ± 0.37 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.7 ms ±   0.1 ms    [User: 27.8 ms, System: 26.9 ms]
  Range (min … max):    27.4 ms …  28.0 ms    96 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):      27.9 ms ±   0.2 ms    [User: 30.4 ms, System: 31.3 ms]
  Range (min … max):    27.5 ms …  28.6 ms    96 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.5 ms, System: 3.2 ms]
  Range (min … max):     7.0 ms …   7.8 ms    283 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
  Time (mean ± σ):     129.8 ms ±   0.5 ms    [User: 96.0 ms, System: 65.7 ms]
  Range (min … max):   128.7 ms … 131.0 ms    22 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null ran
    3.88 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
    3.90 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null
   18.16 ± 0.23 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f1 | >/dev/null

-------------------------------- 4096 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.6 ms ±   0.2 ms    [User: 36.4 ms, System: 30.5 ms]
  Range (min … max):    29.3 ms …  30.2 ms    90 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.5 ms ±   0.2 ms    [User: 35.7 ms, System: 33.7 ms]
  Range (min … max):    29.0 ms …  30.0 ms    91 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.2 ms, System: 4.7 ms]
  Range (min … max):     8.2 ms …   9.2 ms    254 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     153.9 ms ±   6.5 ms    [User: 138.4 ms, System: 70.9 ms]
  Range (min … max):   147.7 ms … 163.0 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    3.51 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    3.52 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   18.34 ± 0.81 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.5 ms ±   0.2 ms    [User: 35.5 ms, System: 31.2 ms]
  Range (min … max):    29.2 ms …  30.1 ms    90 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.7 ms ±   0.4 ms    [User: 36.2 ms, System: 33.5 ms]
  Range (min … max):    28.9 ms …  30.5 ms    89 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.2 ms, System: 4.7 ms]
  Range (min … max):     8.3 ms …   8.8 ms    253 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     176.4 ms ±   1.4 ms    [User: 169.8 ms, System: 76.4 ms]
  Range (min … max):   175.1 ms … 181.1 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    3.52 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    3.55 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   21.03 ± 0.26 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.6 ms ±   0.1 ms    [User: 36.5 ms, System: 30.3 ms]
  Range (min … max):    29.3 ms …  30.0 ms    91 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.6 ms ±   0.3 ms    [User: 36.0 ms, System: 33.3 ms]
  Range (min … max):    29.1 ms …  30.6 ms    90 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.2 ms    [User: 5.4 ms, System: 4.5 ms]
  Range (min … max):     8.2 ms …  10.2 ms    254 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     162.5 ms ±   0.6 ms    [User: 151.7 ms, System: 73.7 ms]
  Range (min … max):   161.0 ms … 163.6 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    3.52 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    3.52 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   19.36 ± 0.37 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.5 ms ±   0.1 ms    [User: 35.2 ms, System: 31.5 ms]
  Range (min … max):    29.1 ms …  29.9 ms    90 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.7 ms ±   0.4 ms    [User: 35.9 ms, System: 33.5 ms]
  Range (min … max):    29.0 ms …  30.6 ms    89 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.4 ms, System: 4.5 ms]
  Range (min … max):     8.2 ms …   9.4 ms    254 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     176.0 ms ±   1.2 ms    [User: 172.5 ms, System: 72.9 ms]
  Range (min … max):   174.4 ms … 179.3 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    3.52 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    3.54 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   20.98 ± 0.33 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.6 ms ±   0.2 ms    [User: 35.5 ms, System: 31.5 ms]
  Range (min … max):    29.1 ms …  30.7 ms    91 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.5 ms ±   0.3 ms    [User: 35.9 ms, System: 33.5 ms]
  Range (min … max):    29.0 ms …  30.4 ms    91 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.2 ms, System: 4.7 ms]
  Range (min … max):     8.2 ms …   9.1 ms    253 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     162.5 ms ±   0.7 ms    [User: 150.7 ms, System: 73.9 ms]
  Range (min … max):   161.4 ms … 163.9 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    3.53 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    3.53 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   19.43 ± 0.26 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.6 ms ±   0.2 ms    [User: 34.7 ms, System: 32.0 ms]
  Range (min … max):    29.2 ms …  30.4 ms    91 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.5 ms ±   0.3 ms    [User: 35.9 ms, System: 33.8 ms]
  Range (min … max):    29.0 ms …  30.5 ms    89 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.3 ms, System: 4.6 ms]
  Range (min … max):     8.2 ms …   8.9 ms    253 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     162.8 ms ±   1.1 ms    [User: 150.8 ms, System: 72.3 ms]
  Range (min … max):   161.2 ms … 165.9 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    3.53 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    3.53 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   19.43 ± 0.24 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.0 ms ±   0.2 ms    [User: 35.3 ms, System: 27.3 ms]
  Range (min … max):    28.7 ms …  30.1 ms    92 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      28.8 ms ±   0.2 ms    [User: 35.5 ms, System: 29.8 ms]
  Range (min … max):    28.5 ms …  29.3 ms    92 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):       7.2 ms ±   0.1 ms    [User: 4.8 ms, System: 3.2 ms]
  Range (min … max):     7.0 ms …   8.3 ms    283 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     150.0 ms ±   0.7 ms    [User: 121.8 ms, System: 73.1 ms]
  Range (min … max):   148.8 ms … 151.7 ms    19 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    4.02 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    4.04 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   20.89 ± 0.44 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.0 ms ±   0.2 ms    [User: 35.4 ms, System: 27.6 ms]
  Range (min … max):    28.7 ms …  29.8 ms    91 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      28.9 ms ±   0.2 ms    [User: 36.1 ms, System: 29.8 ms]
  Range (min … max):    28.5 ms …  29.9 ms    93 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):       7.2 ms ±   0.2 ms    [User: 4.9 ms, System: 3.1 ms]
  Range (min … max):     7.0 ms …  10.0 ms    282 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     162.6 ms ±   0.7 ms    [User: 150.8 ms, System: 71.8 ms]
  Range (min … max):   160.8 ms … 163.6 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    4.03 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    4.05 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   22.69 ± 0.63 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.6 ms ±   0.2 ms    [User: 35.9 ms, System: 31.1 ms]
  Range (min … max):    29.3 ms …  30.9 ms    91 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.4 ms ±   0.2 ms    [User: 35.8 ms, System: 33.6 ms]
  Range (min … max):    29.0 ms …  30.2 ms    91 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.6 ms, System: 4.4 ms]
  Range (min … max):     8.3 ms …   9.1 ms    254 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     149.9 ms ±   0.8 ms    [User: 122.9 ms, System: 70.8 ms]
  Range (min … max):   148.1 ms … 151.4 ms    19 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    3.48 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    3.51 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   17.75 ± 0.22 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.1 ms ±   0.2 ms    [User: 35.5 ms, System: 27.8 ms]
  Range (min … max):    28.7 ms …  30.2 ms    92 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      28.9 ms ±   0.2 ms    [User: 37.1 ms, System: 28.9 ms]
  Range (min … max):    28.4 ms …  29.5 ms    92 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.9 ms, System: 3.0 ms]
  Range (min … max):     7.0 ms …   8.3 ms    286 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     162.6 ms ±   1.2 ms    [User: 151.5 ms, System: 71.0 ms]
  Range (min … max):   161.2 ms … 165.5 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    4.04 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    4.07 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   22.77 ± 0.41 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      29.6 ms ±   0.2 ms    [User: 35.7 ms, System: 31.2 ms]
  Range (min … max):    29.2 ms …  30.4 ms    90 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):      30.4 ms ±   0.7 ms    [User: 37.0 ms, System: 33.3 ms]
  Range (min … max):    29.1 ms …  31.3 ms    91 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.2 ms, System: 4.7 ms]
  Range (min … max):     7.6 ms …   9.1 ms    251 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
  Time (mean ± σ):     182.0 ms ±   1.0 ms    [User: 145.4 ms, System: 66.6 ms]
  Range (min … max):   179.7 ms … 184.4 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null ran
    3.50 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
    3.60 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null
   21.56 ± 0.31 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f2 | >/dev/null

-------------------------------- 16384 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.8 ms ±   0.4 ms    [User: 72.4 ms, System: 60.7 ms]
  Range (min … max):    36.9 ms …  38.8 ms    72 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.9 ms ±   0.4 ms    [User: 78.5 ms, System: 74.9 ms]
  Range (min … max):    36.9 ms …  38.9 ms    71 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.6 ms, System: 4.5 ms]
  Range (min … max):     8.2 ms …   9.2 ms    254 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     162.2 ms ±   0.6 ms    [User: 147.3 ms, System: 70.5 ms]
  Range (min … max):   161.2 ms … 163.5 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    4.51 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    4.53 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   19.37 ± 0.24 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.7 ms ±   0.5 ms    [User: 72.4 ms, System: 60.3 ms]
  Range (min … max):    36.9 ms …  39.1 ms    74 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      38.0 ms ±   0.6 ms    [User: 79.0 ms, System: 74.9 ms]
  Range (min … max):    37.0 ms …  40.0 ms    71 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.6 ms, System: 4.6 ms]
  Range (min … max):     8.2 ms …   8.9 ms    254 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     175.9 ms ±   1.2 ms    [User: 171.3 ms, System: 74.8 ms]
  Range (min … max):   173.7 ms … 179.1 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    4.49 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    4.53 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   20.97 ± 0.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.8 ms ±   0.5 ms    [User: 73.2 ms, System: 60.1 ms]
  Range (min … max):    37.0 ms …  39.3 ms    72 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      38.0 ms ±   0.5 ms    [User: 80.6 ms, System: 73.4 ms]
  Range (min … max):    37.0 ms …  39.1 ms    72 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.5 ms, System: 4.6 ms]
  Range (min … max):     8.2 ms …   9.1 ms    254 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     162.5 ms ±   0.8 ms    [User: 155.6 ms, System: 70.0 ms]
  Range (min … max):   161.1 ms … 164.0 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    4.51 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    4.53 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   19.38 ± 0.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.8 ms ±   0.5 ms    [User: 72.9 ms, System: 60.3 ms]
  Range (min … max):    36.7 ms …  38.9 ms    74 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.9 ms ±   0.5 ms    [User: 77.3 ms, System: 75.2 ms]
  Range (min … max):    37.0 ms …  39.0 ms    72 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.5 ms, System: 4.6 ms]
  Range (min … max):     7.6 ms …   8.9 ms    254 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     176.1 ms ±   1.1 ms    [User: 171.5 ms, System: 74.4 ms]
  Range (min … max):   174.2 ms … 178.0 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    4.51 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    4.52 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   21.00 ± 0.28 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.7 ms ±   0.5 ms    [User: 73.0 ms, System: 60.0 ms]
  Range (min … max):    36.9 ms …  39.2 ms    72 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      38.0 ms ±   0.5 ms    [User: 79.2 ms, System: 74.0 ms]
  Range (min … max):    37.2 ms …  39.3 ms    72 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.8 ms, System: 4.4 ms]
  Range (min … max):     8.2 ms …   9.9 ms    253 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     162.6 ms ±   0.8 ms    [User: 151.5 ms, System: 73.5 ms]
  Range (min … max):   160.6 ms … 164.0 ms    17 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    4.49 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    4.52 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   19.35 ± 0.35 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.8 ms ±   0.5 ms    [User: 73.8 ms, System: 59.6 ms]
  Range (min … max):    36.9 ms …  39.0 ms    73 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      38.0 ms ±   0.5 ms    [User: 79.5 ms, System: 73.4 ms]
  Range (min … max):    37.0 ms …  39.3 ms    72 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.5 ms, System: 4.6 ms]
  Range (min … max):     8.2 ms …   9.2 ms    254 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     162.5 ms ±   1.2 ms    [User: 150.9 ms, System: 72.0 ms]
  Range (min … max):   160.4 ms … 165.6 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    4.51 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    4.53 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   19.38 ± 0.29 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.1 ms ±   0.5 ms    [User: 71.4 ms, System: 54.2 ms]
  Range (min … max):    36.3 ms …  38.9 ms    75 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.3 ms ±   0.5 ms    [User: 76.8 ms, System: 68.2 ms]
  Range (min … max):    36.4 ms …  38.5 ms    72 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       7.2 ms ±   0.1 ms    [User: 5.0 ms, System: 3.0 ms]
  Range (min … max):     7.0 ms …   8.0 ms    283 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     149.2 ms ±   0.9 ms    [User: 122.2 ms, System: 72.0 ms]
  Range (min … max):   147.8 ms … 151.4 ms    19 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    5.16 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    5.19 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   20.78 ± 0.35 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.2 ms ±   0.4 ms    [User: 71.2 ms, System: 54.7 ms]
  Range (min … max):    36.5 ms …  38.0 ms    72 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.3 ms ±   0.4 ms    [User: 76.5 ms, System: 68.8 ms]
  Range (min … max):    36.5 ms …  38.5 ms    74 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       7.2 ms ±   0.1 ms    [User: 4.9 ms, System: 3.1 ms]
  Range (min … max):     7.0 ms …   8.0 ms    285 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     162.8 ms ±   0.9 ms    [User: 150.0 ms, System: 73.1 ms]
  Range (min … max):   161.5 ms … 164.1 ms    17 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    5.18 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    5.19 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   22.68 ± 0.37 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.8 ms ±   0.5 ms    [User: 73.2 ms, System: 59.9 ms]
  Range (min … max):    36.8 ms …  39.8 ms    71 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      38.0 ms ±   0.5 ms    [User: 78.9 ms, System: 74.3 ms]
  Range (min … max):    37.0 ms …  40.2 ms    71 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.4 ms, System: 4.8 ms]
  Range (min … max):     8.3 ms …   9.0 ms    250 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     149.0 ms ±   1.1 ms    [User: 123.4 ms, System: 69.3 ms]
  Range (min … max):   147.6 ms … 152.0 ms    19 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    4.49 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    4.52 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   17.72 ± 0.24 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.0 ms ±   0.4 ms    [User: 71.4 ms, System: 54.1 ms]
  Range (min … max):    36.3 ms …  38.2 ms    74 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.3 ms ±   0.5 ms    [User: 76.7 ms, System: 68.6 ms]
  Range (min … max):    36.7 ms …  39.0 ms    72 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.9 ms, System: 3.0 ms]
  Range (min … max):     7.0 ms …   7.8 ms    280 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     162.5 ms ±   0.8 ms    [User: 150.7 ms, System: 71.9 ms]
  Range (min … max):   161.3 ms … 164.2 ms    17 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    5.19 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    5.23 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   22.78 ± 0.37 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.7 ms ±   0.4 ms    [User: 73.5 ms, System: 59.8 ms]
  Range (min … max):    36.9 ms …  39.3 ms    72 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):      37.9 ms ±   0.5 ms    [User: 78.4 ms, System: 74.9 ms]
  Range (min … max):    37.0 ms …  39.3 ms    73 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.7 ms, System: 4.5 ms]
  Range (min … max):     8.3 ms …   9.0 ms    253 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
  Time (mean ± σ):     189.4 ms ±   1.4 ms    [User: 207.0 ms, System: 74.8 ms]
  Range (min … max):   187.9 ms … 193.8 ms    15 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null ran
    4.46 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
    4.49 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null
   22.43 ± 0.29 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f3 | >/dev/null

-------------------------------- 65536 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.2 ms ±   1.3 ms    [User: 209.6 ms, System: 144.9 ms]
  Range (min … max):    69.1 ms …  73.5 ms    39 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.2 ms ±   1.0 ms    [User: 215.6 ms, System: 186.8 ms]
  Range (min … max):    69.2 ms …  73.7 ms    40 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.7 ms, System: 4.4 ms]
  Range (min … max):     8.3 ms …   9.2 ms    253 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     163.1 ms ±   0.7 ms    [User: 154.5 ms, System: 72.7 ms]
  Range (min … max):   162.0 ms … 164.9 ms    17 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    8.48 ± 0.19 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    8.48 ± 0.16 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   19.43 ± 0.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.4 ms ±   1.4 ms    [User: 210.6 ms, System: 144.6 ms]
  Range (min … max):    68.3 ms …  74.0 ms    40 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.3 ms ±   0.9 ms    [User: 214.4 ms, System: 187.0 ms]
  Range (min … max):    69.2 ms …  73.5 ms    40 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.5 ms, System: 4.6 ms]
  Range (min … max):     8.2 ms …   9.0 ms    252 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     189.7 ms ±   0.8 ms    [User: 201.7 ms, System: 74.7 ms]
  Range (min … max):   188.7 ms … 191.3 ms    15 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    8.49 ± 0.15 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    8.50 ± 0.19 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   22.59 ± 0.26 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.2 ms ±   1.8 ms    [User: 210.9 ms, System: 144.0 ms]
  Range (min … max):    67.3 ms …  74.6 ms    39 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.2 ms ±   1.0 ms    [User: 216.0 ms, System: 185.7 ms]
  Range (min … max):    69.0 ms …  74.0 ms    40 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.5 ms, System: 4.7 ms]
  Range (min … max):     8.3 ms …   9.0 ms    254 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     176.8 ms ±   0.8 ms    [User: 177.3 ms, System: 74.5 ms]
  Range (min … max):   175.7 ms … 178.4 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    8.47 ± 0.15 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    8.47 ± 0.24 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   21.03 ± 0.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.2 ms ±   1.4 ms    [User: 209.5 ms, System: 145.0 ms]
  Range (min … max):    68.7 ms …  73.6 ms    39 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.2 ms ±   1.2 ms    [User: 215.8 ms, System: 185.0 ms]
  Range (min … max):    69.2 ms …  74.5 ms    41 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.8 ms, System: 4.4 ms]
  Range (min … max):     8.3 ms …   9.1 ms    253 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     189.7 ms ±   0.9 ms    [User: 202.0 ms, System: 74.5 ms]
  Range (min … max):   188.7 ms … 191.9 ms    15 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    8.45 ± 0.18 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    8.46 ± 0.20 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   22.52 ± 0.31 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.3 ms ±   1.3 ms    [User: 210.8 ms, System: 144.8 ms]
  Range (min … max):    68.8 ms …  73.7 ms    40 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.1 ms ±   1.2 ms    [User: 217.1 ms, System: 183.3 ms]
  Range (min … max):    68.8 ms …  73.5 ms    40 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.7 ms, System: 4.5 ms]
  Range (min … max):     8.2 ms …   9.1 ms    252 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     176.5 ms ±   0.9 ms    [User: 173.8 ms, System: 76.7 ms]
  Range (min … max):   175.2 ms … 178.2 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    8.43 ± 0.19 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    8.46 ± 0.20 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   20.92 ± 0.34 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.6 ms ±   1.7 ms    [User: 210.9 ms, System: 144.9 ms]
  Range (min … max):    67.9 ms …  76.2 ms    40 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.4 ms ±   1.2 ms    [User: 217.7 ms, System: 184.3 ms]
  Range (min … max):    69.1 ms …  73.5 ms    40 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.5 ms, System: 4.7 ms]
  Range (min … max):     7.8 ms …   8.8 ms    253 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     176.4 ms ±   1.0 ms    [User: 174.3 ms, System: 73.8 ms]
  Range (min … max):   175.2 ms … 178.7 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    8.51 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    8.53 ± 0.22 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   21.02 ± 0.26 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      70.1 ms ±   1.4 ms    [User: 201.2 ms, System: 123.2 ms]
  Range (min … max):    67.1 ms …  73.6 ms    41 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      69.7 ms ±   0.9 ms    [User: 208.4 ms, System: 161.2 ms]
  Range (min … max):    67.8 ms …  71.9 ms    41 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):       7.2 ms ±   0.2 ms    [User: 5.0 ms, System: 3.0 ms]
  Range (min … max):     7.0 ms …   9.8 ms    284 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     149.6 ms ±   0.6 ms    [User: 125.5 ms, System: 70.9 ms]
  Range (min … max):   148.4 ms … 150.5 ms    19 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    9.70 ± 0.29 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    9.75 ± 0.32 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   20.81 ± 0.56 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      69.9 ms ±   1.6 ms    [User: 200.6 ms, System: 123.0 ms]
  Range (min … max):    66.7 ms …  73.4 ms    41 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      69.7 ms ±   1.1 ms    [User: 208.3 ms, System: 162.7 ms]
  Range (min … max):    67.8 ms …  72.3 ms    41 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):       7.2 ms ±   0.1 ms    [User: 4.9 ms, System: 3.0 ms]
  Range (min … max):     7.0 ms …   8.3 ms    285 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     176.6 ms ±   1.2 ms    [User: 173.9 ms, System: 74.1 ms]
  Range (min … max):   174.5 ms … 179.8 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    9.75 ± 0.23 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    9.77 ± 0.29 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   24.68 ± 0.47 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.6 ms ±   1.8 ms    [User: 211.5 ms, System: 144.9 ms]
  Range (min … max):    68.4 ms …  77.4 ms    40 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.0 ms ±   0.9 ms    [User: 217.8 ms, System: 183.6 ms]
  Range (min … max):    69.3 ms …  73.0 ms    40 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.6 ms, System: 4.6 ms]
  Range (min … max):     7.4 ms …   9.2 ms    274 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     149.5 ms ±   0.6 ms    [User: 122.3 ms, System: 72.4 ms]
  Range (min … max):   148.5 ms … 150.7 ms    19 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    8.42 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    8.51 ± 0.26 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   17.75 ± 0.30 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      70.1 ms ±   1.3 ms    [User: 201.9 ms, System: 122.8 ms]
  Range (min … max):    67.4 ms …  74.1 ms    40 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      70.0 ms ±   1.4 ms    [User: 208.9 ms, System: 164.3 ms]
  Range (min … max):    67.6 ms …  74.0 ms    41 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 5.0 ms, System: 3.0 ms]
  Range (min … max):     7.0 ms …   7.6 ms    285 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     176.6 ms ±   0.8 ms    [User: 172.3 ms, System: 74.4 ms]
  Range (min … max):   175.3 ms … 178.2 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    9.86 ± 0.22 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    9.86 ± 0.21 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   24.85 ± 0.30 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      71.2 ms ±   1.5 ms    [User: 209.9 ms, System: 145.5 ms]
  Range (min … max):    68.5 ms …  74.1 ms    40 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):      70.9 ms ±   1.1 ms    [User: 216.6 ms, System: 185.4 ms]
  Range (min … max):    68.9 ms …  72.8 ms    40 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):       8.5 ms ±   0.1 ms    [User: 5.6 ms, System: 4.6 ms]
  Range (min … max):     7.8 ms …   9.1 ms    250 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
  Time (mean ± σ):     231.2 ms ±   1.1 ms    [User: 272.4 ms, System: 82.0 ms]
  Range (min … max):   229.2 ms … 233.1 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null ran
    8.38 ± 0.16 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
    8.42 ± 0.20 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null
   27.33 ± 0.35 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f4 | >/dev/null

-------------------------------- 262144 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     212.7 ms ±   3.7 ms    [User: 788.1 ms, System: 484.7 ms]
  Range (min … max):   206.2 ms … 219.5 ms    13 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     217.5 ms ±   5.9 ms    [User: 788.1 ms, System: 526.7 ms]
  Range (min … max):   206.7 ms … 225.7 ms    13 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.6 ms, System: 4.6 ms]
  Range (min … max):     8.2 ms …   9.5 ms    255 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     162.8 ms ±   0.7 ms    [User: 146.7 ms, System: 74.7 ms]
  Range (min … max):   161.7 ms … 164.3 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   19.40 ± 0.30 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.35 ± 0.58 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.93 ± 0.80 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     216.0 ms ±   5.9 ms    [User: 788.9 ms, System: 492.4 ms]
  Range (min … max):   206.6 ms … 227.6 ms    13 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     219.5 ms ±   6.5 ms    [User: 796.1 ms, System: 527.0 ms]
  Range (min … max):   210.6 ms … 233.7 ms    13 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):       8.3 ms ±   0.1 ms    [User: 5.5 ms, System: 4.7 ms]
  Range (min … max):     8.2 ms …   9.0 ms    253 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     176.0 ms ±   1.1 ms    [User: 176.3 ms, System: 75.6 ms]
  Range (min … max):   174.7 ms … 178.3 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   21.08 ± 0.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.87 ± 0.75 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   26.29 ± 0.82 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     215.7 ms ±   7.2 ms    [User: 796.8 ms, System: 484.6 ms]
  Range (min … max):   203.4 ms … 227.1 ms    13 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     216.9 ms ±   4.8 ms    [User: 787.4 ms, System: 525.5 ms]
  Range (min … max):   205.8 ms … 223.7 ms    13 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.7 ms, System: 4.5 ms]
  Range (min … max):     8.3 ms …   9.2 ms    254 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     162.8 ms ±   0.6 ms    [User: 155.4 ms, System: 74.6 ms]
  Range (min … max):   161.9 ms … 164.0 ms    17 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   19.42 ± 0.24 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.73 ± 0.91 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.87 ± 0.65 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     214.5 ms ±   6.1 ms    [User: 800.2 ms, System: 480.9 ms]
  Range (min … max):   201.1 ms … 223.0 ms    13 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     215.2 ms ±   4.0 ms    [User: 788.4 ms, System: 521.1 ms]
  Range (min … max):   207.9 ms … 221.9 ms    14 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.4 ms, System: 4.8 ms]
  Range (min … max):     8.2 ms …   9.0 ms    254 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     176.0 ms ±   0.4 ms    [User: 174.8 ms, System: 77.1 ms]
  Range (min … max):   175.3 ms … 176.8 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   20.99 ± 0.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.59 ± 0.78 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.68 ± 0.56 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     215.6 ms ±   5.5 ms    [User: 794.0 ms, System: 484.5 ms]
  Range (min … max):   207.4 ms … 227.3 ms    13 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     217.0 ms ±   4.1 ms    [User: 784.6 ms, System: 530.2 ms]
  Range (min … max):   211.6 ms … 226.4 ms    13 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):       8.4 ms ±   0.2 ms    [User: 5.6 ms, System: 4.6 ms]
  Range (min … max):     8.2 ms …  10.6 ms    255 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     162.8 ms ±   0.7 ms    [User: 155.9 ms, System: 73.5 ms]
  Range (min … max):   161.4 ms … 164.2 ms    17 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   19.39 ± 0.42 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.68 ± 0.85 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.84 ± 0.74 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     217.2 ms ±   8.4 ms    [User: 800.0 ms, System: 483.2 ms]
  Range (min … max):   207.2 ms … 235.5 ms    13 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     217.4 ms ±   3.9 ms    [User: 787.6 ms, System: 525.0 ms]
  Range (min … max):   211.4 ms … 223.6 ms    13 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.3 ms, System: 4.8 ms]
  Range (min … max):     8.2 ms …   9.4 ms    254 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     163.0 ms ±   1.1 ms    [User: 154.2 ms, System: 73.2 ms]
  Range (min … max):   161.8 ms … 165.4 ms    17 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   19.41 ± 0.34 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.87 ± 1.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.89 ± 0.63 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     210.1 ms ±   4.4 ms    [User: 756.0 ms, System: 399.0 ms]
  Range (min … max):   202.7 ms … 219.3 ms    14 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     213.8 ms ±   5.4 ms    [User: 748.1 ms, System: 447.1 ms]
  Range (min … max):   205.4 ms … 228.2 ms    14 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):       7.2 ms ±   0.1 ms    [User: 4.7 ms, System: 3.3 ms]
  Range (min … max):     6.9 ms …   8.2 ms    284 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     150.0 ms ±   0.6 ms    [User: 123.0 ms, System: 73.0 ms]
  Range (min … max):   148.9 ms … 151.6 ms    19 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   20.97 ± 0.39 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   29.35 ± 0.81 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   29.87 ± 0.93 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     211.4 ms ±   5.5 ms    [User: 752.8 ms, System: 412.1 ms]
  Range (min … max):   200.4 ms … 218.8 ms    14 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     212.0 ms ±   3.5 ms    [User: 744.6 ms, System: 450.8 ms]
  Range (min … max):   205.5 ms … 217.7 ms    14 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):       7.2 ms ±   0.1 ms    [User: 4.8 ms, System: 3.2 ms]
  Range (min … max):     7.0 ms …   8.1 ms    284 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     162.9 ms ±   0.6 ms    [User: 154.6 ms, System: 72.7 ms]
  Range (min … max):   161.8 ms … 164.1 ms    18 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   22.76 ± 0.33 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   29.54 ± 0.87 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   29.63 ± 0.64 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     214.5 ms ±   8.5 ms    [User: 792.9 ms, System: 485.8 ms]
  Range (min … max):   195.9 ms … 223.3 ms    13 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     216.8 ms ±   5.0 ms    [User: 782.9 ms, System: 527.5 ms]
  Range (min … max):   208.5 ms … 223.6 ms    13 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.6 ms, System: 4.6 ms]
  Range (min … max):     7.5 ms …   9.1 ms    252 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     149.2 ms ±   0.5 ms    [User: 120.8 ms, System: 72.9 ms]
  Range (min … max):   148.4 ms … 150.1 ms    19 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   17.72 ± 0.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.48 ± 1.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.76 ± 0.70 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     210.1 ms ±   5.5 ms    [User: 762.2 ms, System: 399.9 ms]
  Range (min … max):   199.5 ms … 217.6 ms    14 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     210.1 ms ±   2.8 ms    [User: 746.3 ms, System: 445.0 ms]
  Range (min … max):   205.3 ms … 217.2 ms    14 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):       7.1 ms ±   0.1 ms    [User: 4.7 ms, System: 3.3 ms]
  Range (min … max):     6.9 ms …   7.8 ms    284 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     162.7 ms ±   0.8 ms    [User: 153.4 ms, System: 72.8 ms]
  Range (min … max):   161.6 ms … 164.0 ms    17 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   22.87 ± 0.36 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   29.53 ± 0.59 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   29.53 ± 0.90 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     216.0 ms ±   4.2 ms    [User: 805.1 ms, System: 485.8 ms]
  Range (min … max):   207.8 ms … 220.8 ms    13 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     220.0 ms ±   4.7 ms    [User: 809.7 ms, System: 522.5 ms]
  Range (min … max):   211.5 ms … 227.6 ms    13 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):       8.4 ms ±   0.1 ms    [User: 5.7 ms, System: 4.6 ms]
  Range (min … max):     8.2 ms …   9.0 ms    253 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
  Time (mean ± σ):     203.4 ms ±   1.7 ms    [User: 230.0 ms, System: 76.3 ms]
  Range (min … max):   200.8 ms … 208.1 ms    14 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null ran
   24.19 ± 0.31 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   25.70 ± 0.56 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null
   26.18 ± 0.61 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f5 | >/dev/null

-------------------------------- 586011 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     468.4 ms ±   8.9 ms    [User: 1741.5 ms, System: 1082.2 ms]
  Range (min … max):   454.0 ms … 481.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     472.6 ms ±   9.7 ms    [User: 1731.9 ms, System: 1117.0 ms]
  Range (min … max):   456.9 ms … 488.5 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       8.9 ms ±   0.1 ms    [User: 6.1 ms, System: 4.5 ms]
  Range (min … max):     8.7 ms …   9.5 ms    245 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     174.4 ms ±   1.0 ms    [User: 165.1 ms, System: 75.4 ms]
  Range (min … max):   172.6 ms … 177.2 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   19.70 ± 0.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   52.91 ± 1.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   53.38 ± 1.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha1sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     471.4 ms ±  11.8 ms    [User: 1760.6 ms, System: 1087.6 ms]
  Range (min … max):   449.2 ms … 491.0 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     472.6 ms ±   9.4 ms    [User: 1736.8 ms, System: 1122.7 ms]
  Range (min … max):   459.8 ms … 485.8 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       8.9 ms ±   0.1 ms    [User: 6.0 ms, System: 4.6 ms]
  Range (min … max):     8.7 ms …  10.3 ms    244 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     199.4 ms ±   0.6 ms    [User: 211.1 ms, System: 77.6 ms]
  Range (min … max):   197.9 ms … 200.2 ms    14 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   22.52 ± 0.33 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   53.23 ± 1.54 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   53.37 ± 1.30 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha256sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     469.1 ms ±  12.3 ms    [User: 1742.3 ms, System: 1087.8 ms]
  Range (min … max):   448.0 ms … 484.4 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     472.1 ms ±   5.8 ms    [User: 1734.5 ms, System: 1118.9 ms]
  Range (min … max):   463.8 ms … 483.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       8.9 ms ±   0.1 ms    [User: 6.1 ms, System: 4.5 ms]
  Range (min … max):     8.7 ms …   9.8 ms    244 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     199.2 ms ±   0.6 ms    [User: 198.0 ms, System: 78.6 ms]
  Range (min … max):   197.9 ms … 200.5 ms    14 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   22.43 ± 0.35 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   52.82 ± 1.60 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   53.16 ± 1.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha512sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     477.6 ms ±  11.3 ms    [User: 1786.5 ms, System: 1082.0 ms]
  Range (min … max):   461.3 ms … 498.4 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     470.0 ms ±  10.0 ms    [User: 1730.0 ms, System: 1126.7 ms]
  Range (min … max):   449.5 ms … 485.1 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       8.9 ms ±   0.1 ms    [User: 5.8 ms, System: 4.8 ms]
  Range (min … max):     8.7 ms …   9.5 ms    244 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     199.3 ms ±   0.7 ms    [User: 209.4 ms, System: 79.1 ms]
  Range (min … max):   198.4 ms … 201.3 ms    14 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   22.41 ± 0.28 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   52.84 ± 1.29 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   53.69 ± 1.42 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha224sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     473.4 ms ±  11.7 ms    [User: 1761.5 ms, System: 1083.9 ms]
  Range (min … max):   451.2 ms … 492.5 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     473.8 ms ±   7.0 ms    [User: 1743.5 ms, System: 1119.2 ms]
  Range (min … max):   465.1 ms … 483.3 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       8.8 ms ±   0.1 ms    [User: 5.9 ms, System: 4.7 ms]
  Range (min … max):     8.7 ms …   9.4 ms    244 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     192.2 ms ±  11.6 ms    [User: 190.5 ms, System: 78.4 ms]
  Range (min … max):   174.4 ms … 200.9 ms    14 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   21.73 ± 1.33 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   53.50 ± 1.44 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   53.55 ± 0.98 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sha384sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     471.7 ms ±  10.9 ms    [User: 1761.2 ms, System: 1083.5 ms]
  Range (min … max):   451.6 ms … 487.2 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     469.3 ms ±   7.5 ms    [User: 1719.5 ms, System: 1115.9 ms]
  Range (min … max):   456.9 ms … 477.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       8.9 ms ±   0.1 ms    [User: 6.1 ms, System: 4.5 ms]
  Range (min … max):     8.7 ms …  10.3 ms    242 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     174.3 ms ±   0.6 ms    [User: 172.1 ms, System: 76.1 ms]
  Range (min … max):   173.3 ms … 175.3 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   19.68 ± 0.34 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   52.98 ± 1.23 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   53.25 ± 1.52 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- md5sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     466.8 ms ±  10.5 ms    [User: 1668.9 ms, System: 903.5 ms]
  Range (min … max):   449.8 ms … 477.9 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     467.8 ms ±   9.0 ms    [User: 1639.9 ms, System: 945.1 ms]
  Range (min … max):   457.3 ms … 485.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       7.3 ms ±   0.1 ms    [User: 4.9 ms, System: 3.2 ms]
  Range (min … max):     7.2 ms …   7.8 ms    282 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     174.6 ms ±   0.6 ms    [User: 148.3 ms, System: 75.1 ms]
  Range (min … max):   173.8 ms … 175.7 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   23.95 ± 0.27 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   64.02 ± 1.60 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   64.16 ± 1.42 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -s  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     463.4 ms ±  11.9 ms    [User: 1669.4 ms, System: 910.2 ms]
  Range (min … max):   443.4 ms … 487.3 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     463.2 ms ±   9.4 ms    [User: 1635.1 ms, System: 951.4 ms]
  Range (min … max):   449.4 ms … 474.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       7.3 ms ±   0.1 ms    [User: 5.1 ms, System: 3.0 ms]
  Range (min … max):     7.2 ms …   8.1 ms    261 runs
 
  Warning: The first benchmarking run for this command was significantly slower than the rest (8.1 ms). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     174.7 ms ±   0.8 ms    [User: 173.3 ms, System: 75.3 ms]
  Range (min … max):   173.6 ms … 176.3 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   23.87 ± 0.32 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   63.29 ± 1.51 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   63.32 ± 1.81 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- sum -r  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     473.6 ms ±  13.3 ms    [User: 1751.2 ms, System: 1089.1 ms]
  Range (min … max):   463.4 ms … 495.5 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     473.7 ms ±   7.8 ms    [User: 1720.8 ms, System: 1123.9 ms]
  Range (min … max):   463.8 ms … 491.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       8.8 ms ±   0.1 ms    [User: 6.0 ms, System: 4.6 ms]
  Range (min … max):     8.7 ms …  10.6 ms    245 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     145.0 ms ±   0.7 ms    [User: 118.1 ms, System: 74.2 ms]
  Range (min … max):   143.7 ms … 146.8 ms    20 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   16.41 ± 0.28 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   53.59 ± 1.75 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   53.60 ± 1.25 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     459.2 ms ±  12.2 ms    [User: 1666.2 ms, System: 908.9 ms]
  Range (min … max):   444.7 ms … 483.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     464.5 ms ±   6.6 ms    [User: 1631.2 ms, System: 961.0 ms]
  Range (min … max):   452.3 ms … 472.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       7.3 ms ±   0.1 ms    [User: 4.8 ms, System: 3.3 ms]
  Range (min … max):     7.1 ms …   8.2 ms    280 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     174.6 ms ±   1.2 ms    [User: 171.4 ms, System: 76.5 ms]
  Range (min … max):   172.8 ms … 178.2 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   23.93 ± 0.38 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   62.93 ± 1.90 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   63.66 ± 1.29 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- b2sum  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     474.0 ms ±  10.9 ms    [User: 1810.9 ms, System: 1075.0 ms]
  Range (min … max):   453.1 ms … 493.2 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     472.4 ms ±   9.1 ms    [User: 1755.1 ms, System: 1122.8 ms]
  Range (min … max):   459.0 ms … 485.4 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):       9.0 ms ±   0.1 ms    [User: 6.0 ms, System: 4.7 ms]
  Range (min … max):     8.8 ms …   9.8 ms    243 runs
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
  Time (mean ± σ):     231.9 ms ±   1.8 ms    [User: 278.5 ms, System: 79.3 ms]
  Range (min … max):   229.8 ms … 236.0 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash &&  xargs -P 28 -d $'\n' -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null ran
   25.90 ± 0.42 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  parallel -m -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   52.75 ± 1.26 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null
   52.93 ± 1.44 times faster than . /mnt/ramdisk/forkrun/forkrun.bash &&  forkrun -j - -- cksum -a sm3  <"/mnt/ramdisk/hyperfine"/file_lists/f6 | >/dev/null

-----------------------------------------------------
-------------------- "min" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0274209507    0.0274946577    0.0069611677    0.1275120857    0.0273958706    0.0274762046    0.0069687586    0.1287098596    0.0273262774    0.0275000814    0.0069572554    0.1280193974    0.0274414663    0.0275123493    0.0069301283    0.1283217363    0.0273136440    0.0273336040    0.0069447770    0.1284284860        0.0273902215    0.0274566275    0.0069310765    0.1287542215    0.0267576822    0.0266471942    0.0065858022    0.1273722142    0.0266976334    0.0267143654    0.0065818144    0.1282224034    0.0272652695    0.0275249275    0.0069486365    0.1288139235    0.0267647732    0.0266255942    0.00656290220.1283262512    0.0274266036    0.0274874076    0.0070043556    0.1287196226
4096    0.0292956630    0.0290212810    0.008228442,    0.1476814080    0.0291781913    0.0289381743    0.0082596193    0.1750928853    0.0293015278    0.0290777508    0.0082447378    0.1609634618    0.0291358752    0.0290320452    0.0082194732    0.1744125082    0.0291171674    0.0289887984    0.0081514764    0.1613641494        0.0292337212    0.0290043932    0.0082325912    0.1611950142    0.0286610453    0.0285056513    0.0069953313    0.1488408703    0.0287468702    0.0285331552    0.0069796412    0.1607966222    0.029276966,    0.029009948,    0.0082589019    0.1480964850    0.0287265830    0.0283664070    0.00698363700.161179553,    0.0292247007    0.0290515097    0.0075654747    0.1796965637
16384   0.0368767263    0.0369086103    0.0082443813    0.1611567323    0.0368750081    0.0370408511    0.0082462471    0.1736860951    0.0370468008    0.0370226808    0.0082408298    0.1611328848    0.0366900085    0.0369957775    0.0076085145    0.1741663085    0.0369309029    0.0372121799    0.0082439119    0.1606379769        0.0368806448    0.0370468118    0.0082398658    0.1604474358    0.0363483888    0.0363959448    0.0070435648    0.1477601528    0.0365176184    0.0365276814    0.0070250504    0.1615028904    0.0368230697    0.0369943387    0.0082670907    0.1476126957    0.0362980892    0.0366837632    0.00696422020.1612670702    0.0368508591    0.0370215941    0.0082976021    0.1878975261
65536   0.0690714501    0.0692073541    0.0082613491    0.1620113171    0.0683302574    0.0691918234    0.0082345114    0.1886716394    0.0673006588    0.0690269668    0.0082536918    0.1756764308    0.0686852459    0.0691661869    0.0082781699    0.1886847839    0.0688450073    0.0687974773    0.0082410823    0.1752157263        0.0678776197    0.0690591407    0.0077559977    0.1752232217    0.0671410724    0.0677976924    0.0070048734    0.1484093084    0.0667349368    0.0677541648    0.0069957078    0.1745222108    0.0683764055    0.0693211655    0.0074028305    0.1484744375    0.0673813472    0.0676079272    0.00698229120.1752604502    0.0685182835    0.0688688435    0.0078474665    0.2292066745
262144  0.2061902084    0.2066791804    0.0082406464    0.1616799964    0.2065911166    0.2106428466    0.0082070526    0.1747010536    0.2033524994    0.2057800834    0.0082542934    0.1619427474    0.2010928370    0.2078727190    0.0082294700    0.1753335540    0.2073893521    0.2115571031    0.0082193101    0.1614330151        0.2071806117    0.2113648957    0.0082335567    0.1618141597    0.2026632573    0.2053706293    0.0069074493    0.1488528393    0.2003527680    0.2054826130    0.0070227680    0.1618137250    0.1959477193    0.2084640633    0.0074862553    0.1483844223    0.1994857642    0.2053390372    0.00693516920.1615641452    0.2077870660    0.2115366580    0.0082427210    0.2007545970
586011  0.4540255036    0.4568555006    0.0086866246    0.1726122166    0.4492083899    0.4598069809    0.0087140119    0.1979374409    0.4479564084    0.4637997454    0.0087172174    0.1978804104    0.4613090538    0.4495066198    0.0086980458    0.1983890948    0.4512483733    0.4650580973    0.0086808723    0.1743825803        0.4515965544    0.4569429804    0.0086705104    0.1732668184    0.4497702469    0.4573432769    0.0071512379    0.1737556279    0.4433840209    0.4494061559    0.0071679009    0.1735579219    0.4633594738    0.4637962228    0.0086702788    0.1437149098    0.4446807874    0.4523073804    0.00710676440.1728489994    0.4530814172    0.4590417392    0.0087834762    0.2297711962

-----------------------------------------------------
-------------------- "mean" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0277132107    0.0277858552    0.0071018703    0.1295550273    0.0277044894    0.0278540186    0.0071098658    0.1295842983    0.0276920049    0.0278236021    0.0070977789    0.1296323728    0.0277263916    0.0278384815    0.0071139494    0.1292100740    0.0276860259    0.0277892626    0.0071069827    0.1293864972        0.0277297547    0.0278161965    0.0070968081    0.1296268144    0.0271403124    0.0270063344    0.0067321562    0.1291608812    0.0271420567    0.0270119517    0.0067259268    0.1296140323    0.0277377625    0.0278308026    0.0071155355    0.1298631137    0.0271711969    0.0269747635    0.00670052920.1293771965    0.0276967079    0.0278834759    0.0071459362    0.1297750378
4096    0.0295826462    0.0294633528    0.0083960756    0.1539455858    0.0295453627    0.0297421318    0.0083854431    0.1763760995    0.0295588411    0.0295665018    0.0083949785    0.1624915250    0.0295191535    0.0296863372    0.0083880167    0.1759791483    0.0295555153    0.0295126294    0.0083654498    0.1625071830        0.0295576077    0.0295493045    0.0083772021    0.1627741050    0.0289903984    0.0288407503    0.0071803166    0.1499862122    0.0290472235    0.0289121913    0.0071655459    0.1625991521    0.0296282162    0.0293586796    0.0084461904    0.1498861613    0.0290546978    0.0288779845    0.00714043470.1625818908    0.0295652869    0.0303747549    0.0084408692    0.1819846427
16384   0.0377828126    0.0379045184    0.0083730711    0.1621517076    0.0376981922    0.0380390773    0.0083886536    0.1759018872    0.0378258861    0.0380008151    0.0083854977    0.1625441998    0.0378042386    0.0379067182    0.0083850335    0.1761172830    0.0377419816    0.0379840530    0.0084035756    0.1625778508        0.0378297194    0.0379614867    0.0083824377    0.1624506893    0.0370863504    0.0372997128    0.0071826611    0.1492284082    0.0371653572    0.0372634374    0.0071786546    0.1627955780    0.0377944658    0.0379855715    0.0084100250    0.1490279781    0.0370318031    0.0373438487    0.00713391560.1624941866    0.0376807681    0.0379247231    0.0084419724    0.1893840096
65536   0.0712012130    0.0712375166    0.0083967753    0.1631387986    0.0714058046    0.0712592211    0.0083965401    0.1896667325    0.0712050501    0.0711722864    0.0084066314    0.1768107599    0.0712230683    0.0711819162    0.0084220935    0.1896748471    0.0713362397    0.0710841702    0.0084340216    0.1764805250        0.0715860951    0.0714191981    0.0083931837    0.1764282552    0.0701020926    0.0696922074    0.0071866022    0.1495551594    0.0698925346    0.0697417390    0.0071559619    0.1766394128    0.0716404022    0.0709503445    0.0084226432    0.1494853870    0.0700725979    0.0700342873    0.00710503520.1765858808    0.0712075002    0.0709131746    0.0084593300    0.2311657468
262144  0.2127497438    0.2175451560    0.0083912059    0.1627735690    0.2160058552    0.2195079801    0.0083483998    0.1759721996    0.2157017655    0.2168974311    0.0083830488    0.1627614273    0.2144963730    0.2152203727    0.0083818957    0.1759543682    0.2156406048    0.2169598910    0.0083968205    0.1628222344        0.2172342827    0.2173817777    0.0083968546    0.1629524409    0.2100726424    0.2137820781    0.0071568495    0.1500485781    0.2114394953    0.2120188344    0.0071566928    0.1629109702    0.2144795018    0.2168105512    0.0084178356    0.1491573698    0.2100971100    0.2100916952    0.00711510700.1626972134    0.2160115123    0.2200266478    0.0084058616    0.2033604116
586011  0.4684140950    0.4726072864    0.0088534303    0.1743958571    0.4713591488    0.4725538538    0.0088544755    0.1993615609    0.4690818366    0.4720816718    0.0088810405    0.1992449540    0.4775874434    0.4699660384    0.0088944600    0.1993211705    0.4733654988    0.4737834407    0.0088480394    0.1922299340        0.4716526844    0.4693145366    0.0088576747    0.1743467355    0.4668445909    0.4678019991    0.0072916074    0.1746278841    0.4634109897    0.4632145964    0.0073189507    0.1746791082    0.4735717446    0.4736814244    0.0088371030    0.1450355296    0.4591963758    0.4644916626    0.00729669280.1746082901    0.4739983488    0.4723651151    0.0089551446    0.2319171319

-----------------------------------------------------
-------------------- "max" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0281645037    0.0282109347    0.0076459887    0.1330611127    0.0280792546    0.0287238346    0.0078653846    0.1308650776    0.0281348384    0.0284016764    0.0076795494    0.1343617404    0.0281926133    0.0283055793    0.0081232053    0.1301629243    0.0281383380    0.0281794130    0.0080467190    0.1302481110        0.0289043505    0.0281951035    0.0081028375    0.1319277325    0.0275083152    0.0280373062    0.0077167322    0.1305740012    0.0277097104    0.0279404364    0.0075334184    0.1309132104    0.0282903725    0.0284478735    0.0078140655    0.1306496695    0.0275392202    0.0275800952    0.00754355120.1306779882    0.0280402826    0.0286126716    0.0077753525    0.1309661626
4096    0.0302473940    0.0300050770    0.009228138,    0.1629626700    0.0301160613    0.0305055503    0.0088305883    0.1811286633    0.0300033038    0.0306135218    0.0102109508    0.1636074938    0.0298719442    0.0306319442    0.0093999742    0.1793106252    0.0306572484    0.0303838864    0.0090748844    0.1639097104        0.0303959792    0.0305447952    0.0089226342    0.1659210182    0.0301381763    0.0293416623    0.0082777863    0.1516829623    0.0298198782    0.0298781322    0.0099545982    0.1635863912    0.030873487,    0.030184879,    0.0090718140    0.1514077560    0.030167624,    0.029487859,    0.008261662,0.1654892,      0.0304317667    0.0313432987    0.0090959487    0.1844018407
16384   0.0388193263    0.0388701943    0.0091807753    0.1635219683    0.0390993861    0.0399748751    0.0088753791    0.1790869711    0.0392589498    0.0390905128    0.0090508778    0.1640236468    0.0388549045    0.0390032795    0.0089331575    0.1779570845    0.0391588459    0.0392619319    0.0098734639    0.1639790789        0.0389507328    0.0392532418    0.0092115338    0.1655892888    0.0388964938    0.0384819938    0.0079744768    0.1514448778    0.0380344233    0.0385014434    0.0079890174    0.1641414564    0.0398476957    0.0402191867    0.0089540537    0.1520250177    0.0381803422    0.0389594072    0.00783184820.1642013962    0.0392621841    0.0392867281    0.0089911181    0.1938432001
65536   0.0735198951    0.0737111411    0.0091803271    0.1649102261    0.0740264824    0.0734711554    0.0089508424    0.1912613704    0.0746232198    0.0740410768    0.0089896898    0.1784251838    0.0735979729    0.0745047509    0.0091315449    0.1918894419    0.0737049793    0.0735064033    0.0091471203    0.1782375543        0.0761684577    0.0734507087    0.0087877577    0.1787195767    0.0735928394    0.0718966564    0.0097638694    0.1505049514    0.0733792118    0.0722540988    0.0083106318    0.1798251248    0.0774237955    0.0729635435    0.0092325725    0.1507344355    0.0741403342    0.0739591302    0.00763506720.1781883322    0.0741248265    0.0727507055    0.0091022925    0.2330732395
262144  0.2195346914    0.2256578174    0.0095488074    0.1642628594    0.2275810426    0.2337379196    0.0090271776    0.1783251096    0.2271472794    0.2236912874    0.0091948824    0.1639948344    0.2229764600    0.2218734210    0.0089827020    0.1768259870    0.2273090741    0.2263686231    0.0106288201    0.1641831951        0.2354693637    0.2235874937    0.0094363907    0.1653874627    0.2193236183    0.2281518343    0.0081994763    0.1516010003    0.2187978470    0.2177169730    0.0080531160    0.1640736340    0.2232702813    0.2236407383    0.0091264733    0.1500573463    0.2175666592    0.2172050392    0.00782613020.1639686042    0.2207987870    0.2275881790    0.0090062330    0.2081004520
586011  0.4815881456    0.4885399076    0.0094796276    0.1771576656    0.4910329499    0.4857860779    0.0103005779    0.2001747859    0.4843957564    0.4834093374    0.0097839034    0.2004903024    0.4984476408    0.4850839648    0.0095079348    0.2013141028    0.4924669343    0.4832966123    0.0093902033    0.2008762743        0.4872339254    0.4776443574    0.0102723324    0.1753436014    0.4779297539    0.4854144819    0.0077655159    0.1756960859    0.4873053239    0.4744355939    0.0080902899    0.1763280109    0.4955192678    0.4915601568    0.0105802538    0.1468232048    0.4830866604    0.4724030294    0.00815193140.1782391474    0.4932270422    0.4854440192    0.0098007002    0.2360370882


||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0277132107    0.0277858552    0.0071018703    0.1295550273    xargs is 291.2% faster than forkrun (3.9124x)   forkrun is 366.2% faster than parallel (4.6626x)
sha256sum       0.0277044894    0.0278540186    0.0071098658    0.1295842983    xargs is 289.6% faster than forkrun (3.8966x)   forkrun is 367.7% faster than parallel (4.6773x)
sha512sum       0.0276920049    0.0278236021    0.0070977789    0.1296323728    xargs is 292.0% faster than forkrun (3.9200x)   forkrun is 365.9% faster than parallel (4.6590x)
sha224sum       0.0277263916    0.0278384815    0.0071139494    0.1292100740    xargs is 289.7% faster than forkrun (3.8974x)   forkrun is 366.0% faster than parallel (4.6601x)
sha384sum       0.0276860259    0.0277892626    0.0071069827    0.1293864972    xargs is 291.0% faster than forkrun (3.9101x)   forkrun is 365.5% faster than parallel (4.6559x)
md5sum          0.0277297547    0.0278161965    0.0070968081    0.1296268144    xargs is 290.7% faster than forkrun (3.9073x)   forkrun is 367.4% faster than parallel (4.6746x)
sum -s          0.0271403124    0.0270063344    0.0067321562    0.1291608812    xargs is 301.1% faster than forkrun (4.0115x)   forkrun is 378.2% faster than parallel (4.7826x)
sum -r          0.0271420567    0.0270119517    0.0067259268    0.1296140323    xargs is 303.5% faster than forkrun (4.0354x)   forkrun is 377.5% faster than parallel (4.7753x)
cksum           0.0277377625    0.0278308026    0.0071155355    0.1298631137    xargs is 289.8% faster than forkrun (3.8981x)   forkrun is 368.1% faster than parallel (4.6818x)
b2sum           0.0271711969    0.0269747635    0.0067005292    0.1293771965    xargs is 302.5% faster than forkrun (4.0257x)   forkrun is 379.6% faster than parallel (4.7962x)
cksum -a sm3    0.0276967079    0.0278834759    0.0071459362    0.1297750378    xargs is 287.5% faster than forkrun (3.8758x)   forkrun is 368.5% faster than parallel (4.6855x)

OVERALL         .30313991412    .30361474525    .07704733946    1.4247853461    xargs is 293.4% faster than forkrun (3.9344x)   forkrun is 370.0% faster than parallel (4.7000x)




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0295826462    0.0294633528    0.0083960756    0.1539455858    xargs is 250.9% faster than forkrun (3.5091x)   forkrun is 422.4% faster than parallel (5.2249x)
sha256sum       0.0295453627    0.0297421318    0.0083854431    0.1763760995    xargs is 252.3% faster than forkrun (3.5234x)   forkrun is 496.9% faster than parallel (5.9696x)
sha512sum       0.0295588411    0.0295665018    0.0083949785    0.1624915250    xargs is 252.1% faster than forkrun (3.5210x)   forkrun is 449.7% faster than parallel (5.4972x)
sha224sum       0.0295191535    0.0296863372    0.0083880167    0.1759791483    xargs is 251.9% faster than forkrun (3.5192x)   forkrun is 496.1% faster than parallel (5.9615x)
sha384sum       0.0295555153    0.0295126294    0.0083654498    0.1625071830    xargs is 252.7% faster than forkrun (3.5279x)   forkrun is 450.6% faster than parallel (5.5063x)
md5sum          0.0295576077    0.0295493045    0.0083772021    0.1627741050    xargs is 252.7% faster than forkrun (3.5273x)   forkrun is 450.8% faster than parallel (5.5085x)
sum -s          0.0289903984    0.0288407503    0.0071803166    0.1499862122    xargs is 301.6% faster than forkrun (4.0166x)   forkrun is 420.0% faster than parallel (5.2004x)
sum -r          0.0290472235    0.0289121913    0.0071655459    0.1625991521    xargs is 303.4% faster than forkrun (4.0348x)   forkrun is 462.3% faster than parallel (5.6238x)
cksum           0.0296282162    0.0293586796    0.0084461904    0.1498861613    xargs is 247.5% faster than forkrun (3.4759x)   forkrun is 410.5% faster than parallel (5.1053x)
b2sum           0.0290546978    0.0288779845    0.0071404347    0.1625818908    xargs is 306.9% faster than forkrun (4.0690x)   forkrun is 459.5% faster than parallel (5.5957x)
cksum -a sm3    0.0295652869    0.0303747549    0.0084408692    0.1819846427    xargs is 250.2% faster than forkrun (3.5026x)   forkrun is 515.5% faster than parallel (6.1553x)

OVERALL         .32360494987    .32388461886    .08868052323    1.8011117063    xargs is 264.9% faster than forkrun (3.6491x)   forkrun is 456.5% faster than parallel (5.5657x)




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0377828126    0.0379045184    0.0083730711    0.1621517076    xargs is 352.6% faster than forkrun (4.5269x)   forkrun is 327.7% faster than parallel (4.2778x)
sha256sum       0.0376981922    0.0380390773    0.0083886536    0.1759018872    xargs is 353.4% faster than forkrun (4.5345x)   forkrun is 362.4% faster than parallel (4.6242x)
sha512sum       0.0378258861    0.0380008151    0.0083854977    0.1625441998    xargs is 351.0% faster than forkrun (4.5108x)   forkrun is 329.7% faster than parallel (4.2971x)
sha224sum       0.0378042386    0.0379067182    0.0083850335    0.1761172830    xargs is 350.8% faster than forkrun (4.5085x)   forkrun is 365.8% faster than parallel (4.6586x)
sha384sum       0.0377419816    0.0379840530    0.0084035756    0.1625778508    xargs is 349.1% faster than forkrun (4.4911x)   forkrun is 330.7% faster than parallel (4.3076x)
md5sum          0.0378297194    0.0379614867    0.0083824377    0.1624506893    xargs is 351.2% faster than forkrun (4.5129x)   forkrun is 329.4% faster than parallel (4.2942x)
sum -s          0.0370863504    0.0372997128    0.0071826611    0.1492284082    xargs is 416.3% faster than forkrun (5.1633x)   forkrun is 302.3% faster than parallel (4.0238x)
sum -r          0.0371653572    0.0372634374    0.0071786546    0.1627955780    xargs is 417.7% faster than forkrun (5.1772x)   forkrun is 338.0% faster than parallel (4.3803x)
cksum           0.0377944658    0.0379855715    0.0084100250    0.1490279781    xargs is 351.6% faster than forkrun (4.5167x)   forkrun is 292.3% faster than parallel (3.9232x)
b2sum           0.0370318031    0.0373438487    0.0071339156    0.1624941866    xargs is 419.0% faster than forkrun (5.1909x)   forkrun is 338.7% faster than parallel (4.3879x)
cksum -a sm3    0.0376807681    0.0379247231    0.0084419724    0.1893840096    xargs is 346.3% faster than forkrun (4.4635x)   forkrun is 402.6% faster than parallel (5.0260x)

OVERALL         .41344157581    .41561396265    .08866549838    1.8146737788    xargs is 366.2% faster than forkrun (4.6629x)   forkrun is 338.9% faster than parallel (4.3891x)




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0712012130    0.0712375166    0.0083967753    0.1631387986    xargs is 747.9% faster than forkrun (8.4795x)   forkrun is 129.1% faster than parallel (2.2912x)
sha256sum       0.0714058046    0.0712592211    0.0083965401    0.1896667325    xargs is 748.6% faster than forkrun (8.4867x)   forkrun is 166.1% faster than parallel (2.6616x)
sha512sum       0.0712050501    0.0711722864    0.0084066314    0.1768107599    xargs is 746.6% faster than forkrun (8.4662x)   forkrun is 148.4% faster than parallel (2.4842x)
sha224sum       0.0712230683    0.0711819162    0.0084220935    0.1896748471    xargs is 745.1% faster than forkrun (8.4518x)   forkrun is 166.4% faster than parallel (2.6646x)
sha384sum       0.0713362397    0.0710841702    0.0084340216    0.1764805250    xargs is 745.8% faster than forkrun (8.4581x)   forkrun is 147.3% faster than parallel (2.4739x)
md5sum          0.0715860951    0.0714191981    0.0083931837    0.1764282552    xargs is 752.9% faster than forkrun (8.5290x)   forkrun is 146.4% faster than parallel (2.4645x)
sum -s          0.0701020926    0.0696922074    0.0071866022    0.1495551594    xargs is 869.7% faster than forkrun (9.6975x)   forkrun is 114.5% faster than parallel (2.1459x)
sum -r          0.0698925346    0.0697417390    0.0071559619    0.1766394128    xargs is 874.5% faster than forkrun (9.7459x)   forkrun is 153.2% faster than parallel (2.5327x)
cksum           0.0716404022    0.0709503445    0.0084226432    0.1494853870    xargs is 742.3% faster than forkrun (8.4237x)   forkrun is 110.6% faster than parallel (2.1069x)
b2sum           0.0700725979    0.0700342873    0.0071050352    0.1765858808    xargs is 885.6% faster than forkrun (9.8569x)   forkrun is 152.1% faster than parallel (2.5214x)
cksum -a sm3    0.0712075002    0.0709131746    0.0084593300    0.2311657468    xargs is 738.2% faster than forkrun (8.3828x)   forkrun is 225.9% faster than parallel (3.2598x)

OVERALL         .78087259872    .77868606190    .08877881860    1.9556315056    xargs is 777.1% faster than forkrun (8.7710x)   forkrun is 151.1% faster than parallel (2.5114x)




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.2127497438    0.2175451560    0.0083912059    0.1627735690    xargs is 2492.% faster than forkrun (25.925x)   parallel is 33.64% faster than forkrun (1.3364x)
sha256sum       0.2160058552    0.2195079801    0.0083483998    0.1759721996    xargs is 2487.% faster than forkrun (25.873x)   parallel is 22.74% faster than forkrun (1.2274x)
sha512sum       0.2157017655    0.2168974311    0.0083830488    0.1627614273    xargs is 2473.% faster than forkrun (25.730x)   parallel is 32.52% faster than forkrun (1.3252x)
sha224sum       0.2144963730    0.2152203727    0.0083818957    0.1759543682    xargs is 2459.% faster than forkrun (25.590x)   parallel is 21.90% faster than forkrun (1.2190x)
sha384sum       0.2156406048    0.2169598910    0.0083968205    0.1628222344    xargs is 2468.% faster than forkrun (25.681x)   parallel is 32.43% faster than forkrun (1.3243x)
md5sum          0.2172342827    0.2173817777    0.0083968546    0.1629524409    xargs is 2487.% faster than forkrun (25.870x)   parallel is 33.31% faster than forkrun (1.3331x)
sum -s          0.2100726424    0.2137820781    0.0071568495    0.1500485781    xargs is 2835.% faster than forkrun (29.352x)   parallel is 40.00% faster than forkrun (1.4000x)
sum -r          0.2114394953    0.2120188344    0.0071566928    0.1629109702    xargs is 2854.% faster than forkrun (29.544x)   parallel is 29.78% faster than forkrun (1.2978x)
cksum           0.2144795018    0.2168105512    0.0084178356    0.1491573698    xargs is 2475.% faster than forkrun (25.756x)   parallel is 45.35% faster than forkrun (1.4535x)
b2sum           0.2100971100    0.2100916952    0.0071151070    0.1626972134    xargs is 2852.% faster than forkrun (29.527x)   parallel is 29.13% faster than forkrun (1.2913x)
cksum -a sm3    0.2160115123    0.2200266478    0.0084058616    0.2033604116    xargs is 2469.% faster than forkrun (25.697x)   parallel is 6.221% faster than forkrun (1.0622x)

OVERALL         2.3539288873    2.3762424158    .08855057246    1.8314107829    xargs is 2558.% faster than forkrun (26.582x)   parallel is 28.53% faster than forkrun (1.2853x)




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.4684140950    0.4726072864    0.0088534303    0.1743958571    xargs is 5190.% faster than forkrun (52.907x)   parallel is 168.5% faster than forkrun (2.6859x)
sha256sum       0.4713591488    0.4725538538    0.0088544755    0.1993615609    xargs is 5223.% faster than forkrun (53.233x)   parallel is 136.4% faster than forkrun (2.3643x)
sha512sum       0.4690818366    0.4720816718    0.0088810405    0.1992449540    xargs is 5181.% faster than forkrun (52.818x)   parallel is 135.4% faster than forkrun (2.3542x)
sha224sum       0.4775874434    0.4699660384    0.0088944600    0.1993211705    xargs is 5183.% faster than forkrun (52.838x)   parallel is 135.7% faster than forkrun (2.3578x)
sha384sum       0.4733654988    0.4737834407    0.0088480394    0.1922299340    xargs is 5254.% faster than forkrun (53.546x)   parallel is 146.4% faster than forkrun (2.4646x)
md5sum          0.4716526844    0.4693145366    0.0088576747    0.1743467355    xargs is 5198.% faster than forkrun (52.983x)   parallel is 169.1% faster than forkrun (2.6918x)
sum -s          0.4668445909    0.4678019991    0.0072916074    0.1746278841    xargs is 6302.% faster than forkrun (64.024x)   parallel is 167.3% faster than forkrun (2.6733x)
sum -r          0.4634109897    0.4632145964    0.0073189507    0.1746791082    xargs is 6228.% faster than forkrun (63.289x)   parallel is 165.1% faster than forkrun (2.6518x)
cksum           0.4735717446    0.4736814244    0.0088371030    0.1450355296    xargs is 5258.% faster than forkrun (53.589x)   parallel is 226.5% faster than forkrun (3.2652x)
b2sum           0.4591963758    0.4644916626    0.0072966928    0.1746082901    xargs is 6265.% faster than forkrun (63.657x)   parallel is 166.0% faster than forkrun (2.6601x)
cksum -a sm3    0.4739983488    0.4723651151    0.0089551446    0.2319171319    xargs is 5174.% faster than forkrun (52.747x)   parallel is 103.6% faster than forkrun (2.0367x)

OVERALL         5.1684827574    5.1718616258    .09288861950    2.0397681563    xargs is 5464.% faster than forkrun (55.641x)   parallel is 153.3% faster than forkrun (2.5338x)


-------------------------------- 1024 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha1sum  >/dev/null
  Time (mean ± σ):      73.0 ms ±   0.3 ms    [User: 90.4 ms, System: 40.4 ms]
  Range (min … max):    72.6 ms …  73.9 ms    39 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha1sum  >/dev/null
  Time (mean ± σ):      72.6 ms ±   0.4 ms    [User: 92.9 ms, System: 44.3 ms]
  Range (min … max):    72.1 ms …  74.0 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null
  Time (mean ± σ):      78.7 ms ±   0.4 ms    [User: 64.0 ms, System: 15.2 ms]
  Range (min … max):    78.0 ms …  79.7 ms    36 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha1sum  >/dev/null
  Time (mean ± σ):     198.4 ms ±   0.6 ms    [User: 211.9 ms, System: 148.2 ms]
  Range (min … max):   197.6 ms … 199.5 ms    14 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha1sum  >/dev/null ran
    1.00 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha1sum  >/dev/null
    1.08 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null
    2.73 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha1sum  >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha256sum  >/dev/null
  Time (mean ± σ):     117.9 ms ±   0.5 ms    [User: 157.2 ms, System: 41.2 ms]
  Range (min … max):   117.0 ms … 118.9 ms    24 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha256sum  >/dev/null
  Time (mean ± σ):     116.8 ms ±   0.5 ms    [User: 159.4 ms, System: 45.4 ms]
  Range (min … max):   116.0 ms … 118.2 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
  Time (mean ± σ):     145.0 ms ±   0.6 ms    [User: 130.5 ms, System: 15.0 ms]
  Range (min … max):   144.4 ms … 146.8 ms    20 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha256sum  >/dev/null
  Time (mean ± σ):     262.8 ms ±   0.6 ms    [User: 280.1 ms, System: 148.3 ms]
  Range (min … max):   262.1 ms … 264.2 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha256sum  >/dev/null ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha256sum  >/dev/null
    1.24 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
    2.25 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha256sum  >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha512sum  >/dev/null
  Time (mean ± σ):      91.5 ms ±   0.7 ms    [User: 121.0 ms, System: 38.8 ms]
  Range (min … max):    90.7 ms …  94.0 ms    31 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha512sum  >/dev/null
  Time (mean ± σ):      90.6 ms ±   0.4 ms    [User: 121.0 ms, System: 45.5 ms]
  Range (min … max):    89.9 ms …  91.6 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
  Time (mean ± σ):     107.0 ms ±   0.5 ms    [User: 90.9 ms, System: 16.5 ms]
  Range (min … max):   106.2 ms … 108.4 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha512sum  >/dev/null
  Time (mean ± σ):     225.6 ms ±   0.9 ms    [User: 242.5 ms, System: 146.4 ms]
  Range (min … max):   224.3 ms … 227.8 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha512sum  >/dev/null ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha512sum  >/dev/null
    1.18 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
    2.49 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha512sum  >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha224sum  >/dev/null
  Time (mean ± σ):     117.9 ms ±   0.5 ms    [User: 158.0 ms, System: 40.4 ms]
  Range (min … max):   116.8 ms … 118.9 ms    24 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha224sum  >/dev/null
  Time (mean ± σ):     117.0 ms ±   0.4 ms    [User: 159.2 ms, System: 45.6 ms]
  Range (min … max):   116.1 ms … 117.8 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     145.2 ms ±   1.5 ms    [User: 130.1 ms, System: 15.7 ms]
  Range (min … max):   144.2 ms … 151.1 ms    20 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha224sum  >/dev/null
  Time (mean ± σ):     262.2 ms ±   0.6 ms    [User: 283.7 ms, System: 144.0 ms]
  Range (min … max):   261.3 ms … 263.0 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha224sum  >/dev/null ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha224sum  >/dev/null
    1.24 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
    2.24 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha224sum  >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha384sum  >/dev/null
  Time (mean ± σ):      91.2 ms ±   0.4 ms    [User: 117.0 ms, System: 42.0 ms]
  Range (min … max):    90.4 ms …  92.3 ms    31 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha384sum  >/dev/null
  Time (mean ± σ):      90.6 ms ±   0.5 ms    [User: 120.5 ms, System: 45.0 ms]
  Range (min … max):    89.9 ms …  91.9 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     106.4 ms ±   1.1 ms    [User: 91.5 ms, System: 15.4 ms]
  Range (min … max):   105.5 ms … 111.5 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha384sum  >/dev/null
  Time (mean ± σ):     224.8 ms ±   0.5 ms    [User: 243.3 ms, System: 144.8 ms]
  Range (min … max):   224.0 ms … 225.8 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sha384sum  >/dev/null ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sha384sum  >/dev/null
    1.17 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
    2.48 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sha384sum  >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- md5sum  >/dev/null
  Time (mean ± σ):      89.0 ms ±   0.2 ms    [User: 114.8 ms, System: 39.7 ms]
  Range (min … max):    88.6 ms …  89.7 ms    32 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- md5sum  >/dev/null
  Time (mean ± σ):      88.5 ms ±   0.3 ms    [User: 116.8 ms, System: 44.2 ms]
  Range (min … max):    87.9 ms …  89.3 ms    32 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null
  Time (mean ± σ):     101.8 ms ±   0.4 ms    [User: 87.5 ms, System: 14.8 ms]
  Range (min … max):   100.9 ms … 102.4 ms    28 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- md5sum  >/dev/null
  Time (mean ± σ):     220.6 ms ±   0.5 ms    [User: 233.9 ms, System: 149.0 ms]
  Range (min … max):   219.8 ms … 221.7 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- md5sum  >/dev/null ran
    1.01 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- md5sum  >/dev/null
    1.15 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null
    2.49 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- md5sum  >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -s  >/dev/null
  Time (mean ± σ):      38.3 ms ±   0.2 ms    [User: 40.1 ms, System: 37.4 ms]
  Range (min … max):    38.0 ms …  38.9 ms    71 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -s  >/dev/null
  Time (mean ± σ):      37.5 ms ±   0.3 ms    [User: 40.9 ms, System: 40.1 ms]
  Range (min … max):    37.1 ms …  38.3 ms    73 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null
  Time (mean ± σ):      29.1 ms ±   0.3 ms    [User: 15.5 ms, System: 14.4 ms]
  Range (min … max):    28.5 ms …  30.3 ms    92 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -s  >/dev/null
  Time (mean ± σ):     174.6 ms ±   0.9 ms    [User: 161.3 ms, System: 136.9 ms]
  Range (min … max):   173.5 ms … 176.6 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null ran
    1.29 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -s  >/dev/null
    1.32 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -s  >/dev/null
    6.00 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -s  >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -r  >/dev/null
  Time (mean ± σ):      90.3 ms ±   0.5 ms    [User: 115.3 ms, System: 38.3 ms]
  Range (min … max):    89.7 ms …  92.3 ms    31 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -r  >/dev/null
  Time (mean ± σ):      89.2 ms ±   0.4 ms    [User: 116.9 ms, System: 42.3 ms]
  Range (min … max):    88.5 ms …  90.3 ms    32 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null
  Time (mean ± σ):     102.9 ms ±   0.6 ms    [User: 89.8 ms, System: 13.7 ms]
  Range (min … max):   102.4 ms … 105.5 ms    28 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -r  >/dev/null
  Time (mean ± σ):     222.2 ms ±   0.7 ms    [User: 235.6 ms, System: 138.0 ms]
  Range (min … max):   221.3 ms … 223.4 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- sum -r  >/dev/null ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- sum -r  >/dev/null
    1.15 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null
    2.49 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- sum -r  >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum  >/dev/null
  Time (mean ± σ):      35.7 ms ±   0.3 ms    [User: 34.9 ms, System: 40.5 ms]
  Range (min … max):    35.4 ms …  37.1 ms    76 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum  >/dev/null
  Time (mean ± σ):      35.7 ms ±   0.2 ms    [User: 37.5 ms, System: 44.7 ms]
  Range (min … max):    35.3 ms …  36.5 ms    76 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null
  Time (mean ± σ):      24.8 ms ±   0.3 ms    [User: 11.2 ms, System: 14.3 ms]
  Range (min … max):    24.0 ms …  26.1 ms    105 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum  >/dev/null
  Time (mean ± σ):     174.7 ms ±   1.1 ms    [User: 160.2 ms, System: 145.0 ms]
  Range (min … max):   173.0 ms … 177.0 ms    16 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null ran
    1.44 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum  >/dev/null
    1.44 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum  >/dev/null
    7.05 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum  >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- b2sum  >/dev/null
  Time (mean ± σ):      83.7 ms ±   0.5 ms    [User: 106.9 ms, System: 38.7 ms]
  Range (min … max):    82.7 ms …  84.7 ms    34 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- b2sum  >/dev/null
  Time (mean ± σ):      82.5 ms ±   0.4 ms    [User: 109.2 ms, System: 41.8 ms]
  Range (min … max):    81.7 ms …  83.6 ms    34 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null
  Time (mean ± σ):      95.1 ms ±   0.4 ms    [User: 81.2 ms, System: 14.5 ms]
  Range (min … max):    94.5 ms …  96.4 ms    30 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- b2sum  >/dev/null
  Time (mean ± σ):     213.9 ms ±   0.7 ms    [User: 225.3 ms, System: 140.1 ms]
  Range (min … max):   212.6 ms … 215.1 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- b2sum  >/dev/null ran
    1.01 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- b2sum  >/dev/null
    1.15 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null
    2.59 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- b2sum  >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     189.0 ms ±   0.6 ms    [User: 266.4 ms, System: 39.0 ms]
  Range (min … max):   188.0 ms … 189.8 ms    15 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     187.0 ms ±   0.5 ms    [User: 267.4 ms, System: 46.6 ms]
  Range (min … max):   186.1 ms … 187.7 ms    15 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     250.6 ms ±   0.6 ms    [User: 236.8 ms, System: 14.1 ms]
  Range (min … max):   249.7 ms … 251.4 ms    11 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum -a sm3  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     365.4 ms ±   3.1 ms    [User: 386.0 ms, System: 150.3 ms]
  Range (min … max):   363.7 ms … 374.2 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -- cksum -a sm3  >/dev/null ran
    1.01 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  forkrun -j - -- cksum -a sm3  >/dev/null
    1.34 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
    1.95 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f1 |  parallel -m -- cksum -a sm3  >/dev/null

-------------------------------- 4096 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha1sum  >/dev/null
  Time (mean ± σ):      66.2 ms ±   0.3 ms    [User: 120.1 ms, System: 60.8 ms]
  Range (min … max):    65.7 ms …  67.2 ms    42 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha1sum  >/dev/null
  Time (mean ± σ):      63.2 ms ±   1.2 ms    [User: 122.8 ms, System: 61.7 ms]
  Range (min … max):    61.9 ms …  66.0 ms    44 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null
  Time (mean ± σ):      58.8 ms ±   0.3 ms    [User: 90.7 ms, System: 32.6 ms]
  Range (min … max):    58.3 ms …  59.7 ms    48 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha1sum  >/dev/null
  Time (mean ± σ):     222.8 ms ±   1.3 ms    [User: 290.7 ms, System: 169.2 ms]
  Range (min … max):   220.4 ms … 224.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null ran
    1.07 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha1sum  >/dev/null
    1.13 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha1sum  >/dev/null
    3.79 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha1sum  >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha256sum  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      96.3 ms ±   1.4 ms    [User: 206.8 ms, System: 58.7 ms]
  Range (min … max):    94.1 ms … 103.2 ms    30 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha256sum  >/dev/null
  Time (mean ± σ):      91.6 ms ±   2.2 ms    [User: 208.0 ms, System: 61.3 ms]
  Range (min … max):    85.4 ms …  96.2 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      97.6 ms ±   0.7 ms    [User: 173.9 ms, System: 32.0 ms]
  Range (min … max):    96.9 ms … 100.2 ms    29 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha256sum  >/dev/null
  Time (mean ± σ):     230.0 ms ±   1.0 ms    [User: 374.8 ms, System: 170.8 ms]
  Range (min … max):   228.2 ms … 231.9 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha256sum  >/dev/null ran
    1.05 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha256sum  >/dev/null
    1.07 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
    2.51 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha256sum  >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha512sum  >/dev/null
  Time (mean ± σ):      80.6 ms ±   0.9 ms    [User: 165.0 ms, System: 58.3 ms]
  Range (min … max):    79.8 ms …  83.0 ms    36 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha512sum  >/dev/null
  Time (mean ± σ):      76.1 ms ±   1.7 ms    [User: 162.4 ms, System: 64.6 ms]
  Range (min … max):    71.8 ms …  80.9 ms    38 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
  Time (mean ± σ):      77.6 ms ±   0.4 ms    [User: 130.8 ms, System: 33.7 ms]
  Range (min … max):    76.9 ms …  78.8 ms    37 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha512sum  >/dev/null
  Time (mean ± σ):     223.7 ms ±   2.1 ms    [User: 330.0 ms, System: 173.5 ms]
  Range (min … max):   220.6 ms … 226.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha512sum  >/dev/null ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
    1.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha512sum  >/dev/null
    2.94 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha512sum  >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha224sum  >/dev/null
  Time (mean ± σ):      96.4 ms ±   1.4 ms    [User: 207.9 ms, System: 56.8 ms]
  Range (min … max):    95.1 ms …  99.6 ms    29 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha224sum  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):      91.3 ms ±   1.6 ms    [User: 206.7 ms, System: 61.5 ms]
  Range (min … max):    89.9 ms …  96.3 ms    31 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
  Time (mean ± σ):      97.1 ms ±   0.3 ms    [User: 170.9 ms, System: 34.0 ms]
  Range (min … max):    96.5 ms …  97.8 ms    29 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha224sum  >/dev/null
  Time (mean ± σ):     229.1 ms ±   1.1 ms    [User: 372.9 ms, System: 172.1 ms]
  Range (min … max):   228.0 ms … 231.3 ms    12 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha224sum  >/dev/null ran
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha224sum  >/dev/null
    1.06 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
    2.51 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha224sum  >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha384sum  >/dev/null
  Time (mean ± σ):      79.9 ms ±   1.0 ms    [User: 158.4 ms, System: 61.3 ms]
  Range (min … max):    78.9 ms …  82.2 ms    35 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha384sum  >/dev/null
  Time (mean ± σ):      75.4 ms ±   1.6 ms    [User: 160.5 ms, System: 62.9 ms]
  Range (min … max):    72.7 ms …  79.8 ms    38 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
  Time (mean ± σ):      76.3 ms ±   0.3 ms    [User: 128.3 ms, System: 32.9 ms]
  Range (min … max):    75.9 ms …  77.0 ms    37 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha384sum  >/dev/null
  Time (mean ± σ):     225.0 ms ±   1.5 ms    [User: 329.2 ms, System: 171.8 ms]
  Range (min … max):   222.7 ms … 227.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sha384sum  >/dev/null ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
    1.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sha384sum  >/dev/null
    2.99 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sha384sum  >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- md5sum  >/dev/null
  Time (mean ± σ):      76.7 ms ±   0.7 ms    [User: 149.3 ms, System: 60.0 ms]
  Range (min … max):    75.9 ms …  78.6 ms    37 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- md5sum  >/dev/null
  Time (mean ± σ):      73.6 ms ±   1.7 ms    [User: 148.9 ms, System: 64.3 ms]
  Range (min … max):    71.6 ms …  76.3 ms    37 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null
  Time (mean ± σ):      71.9 ms ±   0.3 ms    [User: 118.7 ms, System: 32.4 ms]
  Range (min … max):    71.4 ms …  72.8 ms    39 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- md5sum  >/dev/null
  Time (mean ± σ):     223.9 ms ±   1.2 ms    [User: 318.3 ms, System: 170.6 ms]
  Range (min … max):   222.1 ms … 225.9 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- md5sum  >/dev/null
    1.07 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- md5sum  >/dev/null
    3.11 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- md5sum  >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -s  >/dev/null
  Time (mean ± σ):      44.4 ms ±   0.2 ms    [User: 60.6 ms, System: 56.5 ms]
  Range (min … max):    43.4 ms …  45.0 ms    62 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -s  >/dev/null
  Time (mean ± σ):      41.8 ms ±   0.5 ms    [User: 60.7 ms, System: 60.7 ms]
  Range (min … max):    40.5 ms …  43.5 ms    66 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null
  Time (mean ± σ):      30.7 ms ±   0.2 ms    [User: 31.4 ms, System: 31.8 ms]
  Range (min … max):    30.1 ms …  31.3 ms    87 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -s  >/dev/null
  Time (mean ± σ):     222.7 ms ±   1.3 ms    [User: 225.4 ms, System: 163.9 ms]
  Range (min … max):   220.8 ms … 224.8 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null ran
    1.36 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -s  >/dev/null
    1.45 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -s  >/dev/null
    7.26 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -s  >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -r  >/dev/null
  Time (mean ± σ):      77.6 ms ±   0.6 ms    [User: 150.0 ms, System: 57.0 ms]
  Range (min … max):    76.8 ms …  79.9 ms    36 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -r  >/dev/null
 
    Time (mean ± σ):      73.5 ms ±   1.6 ms    [User: 151.4 ms, System: 59.7 ms]
  Range (min … max):    68.9 ms …  77.3 ms    39 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null
  Time (mean ± σ):      72.2 ms ±   0.4 ms    [User: 118.2 ms, System: 33.0 ms]
  Range (min … max):    71.7 ms …  73.2 ms    39 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -r  >/dev/null
  Time (mean ± σ):     222.8 ms ±   1.0 ms    [User: 317.2 ms, System: 160.7 ms]
  Range (min … max):   221.8 ms … 225.2 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- sum -r  >/dev/null
    1.07 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- sum -r  >/dev/null
    3.08 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- sum -r  >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum  >/dev/null
  Time (mean ± σ):      41.9 ms ±   0.3 ms    [User: 52.4 ms, System: 59.9 ms]
  Range (min … max):    41.5 ms …  43.0 ms    66 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum  >/dev/null
  Time (mean ± σ):      39.9 ms ±   0.7 ms    [User: 54.3 ms, System: 61.6 ms]
  Range (min … max):    39.3 ms …  41.9 ms    69 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null
  Time (mean ± σ):      27.2 ms ±   0.2 ms    [User: 22.5 ms, System: 33.2 ms]
  Range (min … max):    26.8 ms …  28.3 ms    97 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum  >/dev/null
  Time (mean ± σ):     225.4 ms ±   2.3 ms    [User: 224.8 ms, System: 170.6 ms]
  Range (min … max):   223.0 ms … 232.4 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null ran
    1.47 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum  >/dev/null
    1.54 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum  >/dev/null
    8.29 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum  >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- b2sum  >/dev/null
  Time (mean ± σ):      75.4 ms ±   0.5 ms    [User: 147.9 ms, System: 56.8 ms]
  Range (min … max):    74.3 ms …  77.1 ms    37 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- b2sum  >/dev/null
  Time (mean ± σ):      71.5 ms ±   1.4 ms    [User: 148.8 ms, System: 59.7 ms]
  Range (min … max):    69.8 ms …  74.2 ms    39 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null
  Time (mean ± σ):      70.5 ms ±   0.4 ms    [User: 117.1 ms, System: 31.7 ms]
  Range (min … max):    70.0 ms …  71.9 ms    40 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- b2sum  >/dev/null
  Time (mean ± σ):     223.2 ms ±   1.6 ms    [User: 314.8 ms, System: 161.7 ms]
  Range (min … max):   220.0 ms … 225.6 ms    13 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- b2sum  >/dev/null
    1.07 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- b2sum  >/dev/null
    3.17 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- b2sum  >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     143.1 ms ±   2.0 ms    [User: 334.9 ms, System: 60.4 ms]
  Range (min … max):   141.5 ms … 146.8 ms    19 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum -a sm3  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.  Time (mean ± σ):     134.4 ms ±   3.4 ms    [User: 333.9 ms, System: 65.2 ms]
  Range (min … max):   124.5 ms … 140.6 ms    20 runs

 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     157.7 ms ±   1.2 ms    [User: 301.3 ms, System: 32.7 ms]
  Range (min … max):   157.1 ms … 162.5 ms    18 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     268.2 ms ±   0.9 ms    [User: 502.1 ms, System: 172.9 ms]
  Range (min … max):   267.1 ms … 269.8 ms    11 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -- cksum -a sm3  >/dev/null ran
    1.06 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  forkrun -j - -- cksum -a sm3  >/dev/null
    1.17 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
    2.00 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f2 |  parallel -m -- cksum -a sm3  >/dev/null

-------------------------------- 16384 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha1sum  >/dev/null
  Time (mean ± σ):     186.7 ms ±   0.6 ms    [User: 824.4 ms, System: 218.3 ms]
  Range (min … max):   186.1 ms … 188.0 ms    15 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha1sum  >/dev/null
  Time (mean ± σ):     192.5 ms ±  11.5 ms    [User: 923.2 ms, System: 241.0 ms]
  Range (min … max):   181.8 ms … 208.5 ms    16 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null
  Time (mean ± σ):     238.1 ms ±   0.6 ms    [User: 744.2 ms, System: 172.6 ms]
  Range (min … max):   237.2 ms … 239.4 ms    12 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha1sum  >/dev/null
  Time (mean ± σ):     472.0 ms ±   1.7 ms    [User: 1215.4 ms, System: 363.6 ms]
  Range (min … max):   470.0 ms … 474.9 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha1sum  >/dev/null ran
    1.03 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha1sum  >/dev/null
    1.27 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null
    2.53 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha1sum  >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha256sum  >/dev/null
  Time (mean ± σ):     332.3 ms ±   1.1 ms    [User: 1630.9 ms, System: 220.0 ms]
  Range (min … max):   330.9 ms … 334.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha256sum  >/dev/null
  Time (mean ± σ):     356.1 ms ±  22.4 ms    [User: 1816.3 ms, System: 240.9 ms]
  Range (min … max):   332.2 ms … 385.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
  Time (mean ± σ):     467.0 ms ±   0.9 ms    [User: 1551.9 ms, System: 169.7 ms]
  Range (min … max):   466.0 ms … 469.1 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha256sum  >/dev/null
  Time (mean ± σ):     552.6 ms ±   1.2 ms    [User: 2016.1 ms, System: 392.6 ms]
  Range (min … max):   550.9 ms … 555.4 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha256sum  >/dev/null ran
    1.07 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha256sum  >/dev/null
    1.41 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
    1.66 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha256sum  >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha512sum  >/dev/null
  Time (mean ± σ):     247.7 ms ±   0.5 ms    [User: 1172.6 ms, System: 223.5 ms]
  Range (min … max):   247.0 ms … 248.7 ms    11 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha512sum  >/dev/null
  Time (mean ± σ):     261.8 ms ±  20.2 ms    [User: 1309.7 ms, System: 243.4 ms]
  Range (min … max):   243.7 ms … 303.3 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
  Time (mean ± σ):     331.8 ms ±   0.7 ms    [User: 1097.4 ms, System: 171.7 ms]
  Range (min … max):   330.8 ms … 333.2 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha512sum  >/dev/null
  Time (mean ± σ):     503.3 ms ±   1.9 ms    [User: 1562.8 ms, System: 384.2 ms]
  Range (min … max):   499.2 ms … 506.4 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha512sum  >/dev/null ran
    1.06 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha512sum  >/dev/null
    1.34 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
    2.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha512sum  >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha224sum  >/dev/null
  Time (mean ± σ):     331.7 ms ±   0.6 ms    [User: 1629.3 ms, System: 216.0 ms]
  Range (min … max):   330.7 ms … 332.7 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha224sum  >/dev/null
  Time (mean ± σ):     335.4 ms ±   5.0 ms    [User: 1806.4 ms, System: 232.6 ms]
  Range (min … max):   331.3 ms … 344.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
  Time (mean ± σ):     466.8 ms ±   2.1 ms    [User: 1552.6 ms, System: 166.2 ms]
  Range (min … max):   465.4 ms … 472.6 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha224sum  >/dev/null
  Time (mean ± σ):     553.0 ms ±   2.4 ms    [User: 2020.1 ms, System: 387.8 ms]
  Range (min … max):   550.1 ms … 558.2 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha224sum  >/dev/null ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha224sum  >/dev/null
    1.41 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
    1.67 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha224sum  >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha384sum  >/dev/null
  Time (mean ± σ):     245.6 ms ±   0.5 ms    [User: 1155.1 ms, System: 226.5 ms]
  Range (min … max):   245.0 ms … 246.3 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha384sum  >/dev/null
  Time (mean ± σ):     256.4 ms ±  18.0 ms    [User: 1312.2 ms, System: 232.8 ms]
  Range (min … max):   242.0 ms … 300.8 ms    11 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
  Time (mean ± σ):     330.1 ms ±   0.5 ms    [User: 1086.3 ms, System: 168.7 ms]
  Range (min … max):   329.5 ms … 331.1 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha384sum  >/dev/null
  Time (mean ± σ):     501.9 ms ±   3.1 ms    [User: 1556.3 ms, System: 378.9 ms]
  Range (min … max):   499.3 ms … 509.8 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sha384sum  >/dev/null ran
    1.04 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sha384sum  >/dev/null
    1.34 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
    2.04 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sha384sum  >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- md5sum  >/dev/null
  Time (mean ± σ):     236.4 ms ±   0.8 ms    [User: 1096.4 ms, System: 221.3 ms]
  Range (min … max):   234.8 ms … 237.6 ms    12 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- md5sum  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     236.7 ms ±   4.7 ms    [User: 1141.0 ms, System: 240.5 ms]
  Range (min … max):   233.7 ms … 245.9 ms    12 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null
  Time (mean ± σ):     318.7 ms ±   0.6 ms    [User: 1028.9 ms, System: 166.4 ms]
  Range (min … max):   318.0 ms … 319.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- md5sum  >/dev/null
  Time (mean ± σ):     499.3 ms ±   4.0 ms    [User: 1500.1 ms, System: 366.2 ms]
  Range (min … max):   495.1 ms … 509.4 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- md5sum  >/dev/null ran
    1.00 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- md5sum  >/dev/null
    1.35 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null
    2.11 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- md5sum  >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -s  >/dev/null
  Time (mean ± σ):      81.3 ms ±   0.9 ms    [User: 227.2 ms, System: 219.0 ms]
  Range (min … max):    78.9 ms …  83.1 ms    34 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -s  >/dev/null
  Time (mean ± σ):      75.8 ms ±   4.0 ms    [User: 249.6 ms, System: 245.6 ms]
  Range (min … max):    72.1 ms …  88.0 ms    35 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null
  Time (mean ± σ):      68.6 ms ±   0.3 ms    [User: 157.8 ms, System: 168.4 ms]
  Range (min … max):    68.1 ms …  69.5 ms    41 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -s  >/dev/null
  Time (mean ± σ):     452.7 ms ±   6.0 ms    [User: 610.7 ms, System: 355.3 ms]
  Range (min … max):   448.4 ms … 469.3 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null ran
    1.10 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -s  >/dev/null
    1.18 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -s  >/dev/null
    6.59 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -s  >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -r  >/dev/null
 
  Warning  Time (mean ± σ):     239.6 ms ±   2.3 ms    [User: 1116.7 ms, System: 214.9 ms]
  Range (min … max):   237.8 ms … 246.7 ms    12 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -r  >/dev/null
  Time (mean ± σ):     244.1 ms ±   8.0 ms    [User: 1156.9 ms, System: 236.0 ms]
  Range (min … max):   237.1 ms … 264.1 ms    11 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null
 
  Warning: The first benchmarking run for this command was significantly slower than the rest (331.1 ms). This could be caused by (filesystem) caches that were not filled until after the first run. You are already using both the '--warmup' option as well as the '--prepare' option. Consider re-running the benchmark on a quiet system. Maybe it was a random outlier. Alternatively, consider increasing the warmup count.
  Time (mean ± σ):     324.6 ms ±   2.3 ms    [User: 1043.7 ms, System: 166.1 ms]
  Range (min … max):   323.0 ms … 331.1 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -r  >/dev/null
  Time (mean ± σ):     500.6 ms ±   2.4 ms    [User: 1500.0 ms, System: 365.2 ms]
  Range (min … max):   497.9 ms … 505.7 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- sum -r  >/dev/null ran
    1.02 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- sum -r  >/dev/null
    1.35 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null
    2.09 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- sum -r  >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum  >/dev/null
  Time (mean ± σ):      72.4 ms ±   0.8 ms    [User: 171.5 ms, System: 223.1 ms]
  Range (min … max):    69.6 ms …  74.0 ms    39 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum  >/dev/null
  Time (mean ± σ):      67.3 ms ±   2.8 ms    [User: 186.0 ms, System: 253.2 ms]
  Range (min … max):    64.2 ms …  77.8 ms    42 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null
  Time (mean ± σ):      54.8 ms ±   0.3 ms    [User: 104.9 ms, System: 165.7 ms]
  Range (min … max):    54.2 ms …  55.5 ms    51 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum  >/dev/null
  Time (mean ± σ):     450.2 ms ±   4.2 ms    [User: 552.0 ms, System: 370.5 ms]
  Range (min … max):   445.9 ms … 460.2 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null ran
    1.23 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum  >/dev/null
    1.32 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum  >/dev/null
    8.22 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum  >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- b2sum  >/dev/null
  Time (mean ± σ):     222.0 ms ±   0.7 ms    [User: 1038.9 ms, System: 212.7 ms]
  Range (min … max):   220.8 ms … 222.9 ms    13 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- b2sum  >/dev/null
  Time (mean ± σ):     229.6 ms ±  12.7 ms    [User: 1147.6 ms, System: 236.0 ms]
  Range (min … max):   216.7 ms … 249.4 ms    12 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null
  Time (mean ± σ):     292.0 ms ±   0.5 ms    [User: 951.4 ms, System: 173.9 ms]
  Range (min … max):   291.5 ms … 292.7 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- b2sum  >/dev/null
  Time (mean ± σ):     489.4 ms ±   2.8 ms    [User: 1417.4 ms, System: 363.9 ms]
  Range (min … max):   485.5 ms … 494.3 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- b2sum  >/dev/null ran
    1.03 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- b2sum  >/dev/null
    1.32 ± 0.00 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null
    2.20 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- b2sum  >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     571.9 ms ±   0.7 ms    [User: 2927.4 ms, System: 217.8 ms]
  Range (min … max):   570.6 ms … 573.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     616.2 ms ±  37.6 ms    [User: 3215.0 ms, System: 234.5 ms]
  Range (min … max):   571.0 ms … 649.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.  Time (mean ± σ):     833.9 ms ±   6.0 ms    [User: 2826.4 ms, System: 170.5 ms]
  Range (min … max):   830.8 ms … 850.9 ms    10 runs

 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum -a sm3  >/dev/null
 
  Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
  Time (mean ± σ):     773.6 ms ±   7.9 ms    [User: 3311.8 ms, System: 386.3 ms]
  Range (min … max):   769.7 ms … 794.5 ms    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -j - -- cksum -a sm3  >/dev/null ran
    1.08 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  forkrun -- cksum -a sm3  >/dev/null
    1.35 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  parallel -m -- cksum -a sm3  >/dev/null
    1.46 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f3 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null

-------------------------------- 65536 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha1sum  >/dev/null
  Time (mean ± σ):     318.8 ms ±   2.0 ms    [User: 2696.2 ms, System: 712.7 ms]
  Range (min … max):   314.9 ms … 321.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha1sum  >/dev/null
  Time (mean ± σ):     311.5 ms ±  13.0 ms    [User: 4204.6 ms, System: 890.7 ms]
  Range (min … max):   287.7 ms … 328.8 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null
  Time (mean ± σ):     287.8 ms ±  10.4 ms    [User: 3729.0 ms, System: 739.5 ms]
  Range (min … max):   271.5 ms … 299.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha1sum  >/dev/null
  Time (mean ± σ):      1.368 s ±  0.008 s    [User: 3.839 s, System: 1.039 s]
  Range (min … max):    1.359 s …  1.382 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null ran
    1.08 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha1sum  >/dev/null
    1.11 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha1sum  >/dev/null
    4.75 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha1sum  >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha256sum  >/dev/null
  Time (mean ± σ):     552.1 ms ±   6.2 ms    [User: 5261.8 ms, System: 699.1 ms]
  Range (min … max):   547.1 ms … 566.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha256sum  >/dev/null
  Time (mean ± σ):     527.0 ms ±  21.8 ms    [User: 8404.9 ms, System: 872.9 ms]
  Range (min … max):   505.4 ms … 566.1 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
  Time (mean ± σ):     559.2 ms ±  16.3 ms    [User: 7999.8 ms, System: 706.1 ms]
  Range (min … max):   544.9 ms … 594.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha256sum  >/dev/null
  Time (mean ± σ):      1.437 s ±  0.006 s    [User: 6.435 s, System: 1.064 s]
  Range (min … max):    1.432 s …  1.452 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha256sum  >/dev/null ran
    1.05 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha256sum  >/dev/null
    1.06 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
    2.73 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha256sum  >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha512sum  >/dev/null
  Time (mean ± σ):     425.5 ms ±   4.3 ms    [User: 3874.2 ms, System: 714.9 ms]
  Range (min … max):   418.0 ms … 434.3 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha512sum  >/dev/null
  Time (mean ± σ):     409.5 ms ±  18.6 ms    [User: 6224.4 ms, System: 879.7 ms]
  Range (min … max):   387.1 ms … 439.2 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
  Time (mean ± σ):     421.5 ms ±  15.6 ms    [User: 5713.5 ms, System: 718.7 ms]
  Range (min … max):   395.8 ms … 442.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha512sum  >/dev/null
  Time (mean ± σ):      1.379 s ±  0.008 s    [User: 5.000 s, System: 1.036 s]
  Range (min … max):    1.363 s …  1.389 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha512sum  >/dev/null ran
    1.03 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
    1.04 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha512sum  >/dev/null
    3.37 ± 0.15 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha512sum  >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha224sum  >/dev/null
  Time (mean ± σ):     550.9 ms ±   4.6 ms    [User: 5232.2 ms, System: 723.9 ms]
  Range (min … max):   543.0 ms … 559.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha224sum  >/dev/null
  Time (mean ± σ):     532.2 ms ±  19.6 ms    [User: 8420.7 ms, System: 850.1 ms]
  Range (min … max):   497.7 ms … 560.2 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
  Time (mean ± σ):     559.7 ms ±  10.5 ms    [User: 7891.8 ms, System: 713.9 ms]
  Range (min … max):   549.0 ms … 579.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha224sum  >/dev/null
  Time (mean ± σ):      1.451 s ±  0.020 s    [User: 6.429 s, System: 1.068 s]
  Range (min … max):    1.427 s …  1.485 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha224sum  >/dev/null ran
    1.04 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha224sum  >/dev/null
    1.05 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
    2.73 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha224sum  >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha384sum  >/dev/null
  Time (mean ± σ):     416.8 ms ±   2.7 ms    [User: 3782.5 ms, System: 723.5 ms]
  Range (min … max):   412.5 ms … 421.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha384sum  >/dev/null
  Time (mean ± σ):     403.7 ms ±  18.8 ms    [User: 6106.7 ms, System: 883.4 ms]
  Range (min … max):   371.2 ms … 432.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
  Time (mean ± σ):     407.7 ms ±  17.0 ms    [User: 5611.7 ms, System: 710.1 ms]
  Range (min … max):   387.5 ms … 432.7 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha384sum  >/dev/null
  Time (mean ± σ):      1.376 s ±  0.007 s    [User: 4.930 s, System: 1.049 s]
  Range (min … max):    1.369 s …  1.388 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sha384sum  >/dev/null ran
    1.01 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
    1.03 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sha384sum  >/dev/null
    3.41 ± 0.16 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sha384sum  >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- md5sum  >/dev/null
  Time (mean ± σ):     396.8 ms ±   1.4 ms    [User: 3519.2 ms, System: 720.6 ms]
  Range (min … max):   394.8 ms … 399.2 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- md5sum  >/dev/null
  Time (mean ± σ):     321.8 ms ±   6.9 ms    [User: 4159.6 ms, System: 913.2 ms]
  Range (min … max):   313.3 ms … 330.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null
  Time (mean ± σ):     324.7 ms ±   6.8 ms    [User: 3869.1 ms, System: 733.7 ms]
  Range (min … max):   315.7 ms … 339.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- md5sum  >/dev/null
  Time (mean ± σ):      1.379 s ±  0.019 s    [User: 4.740 s, System: 1.032 s]
  Range (min … max):    1.365 s …  1.431 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- md5sum  >/dev/null ran
    1.01 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null
    1.23 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- md5sum  >/dev/null
    4.28 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- md5sum  >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -s  >/dev/null
  Time (mean ± σ):     146.0 ms ±   1.1 ms    [User: 786.0 ms, System: 719.7 ms]
  Range (min … max):   144.4 ms … 147.9 ms    20 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -s  >/dev/null
  Time (mean ± σ):     128.5 ms ±   2.8 ms    [User: 1000.1 ms, System: 899.8 ms]
  Range (min … max):   123.9 ms … 134.5 ms    23 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null
  Time (mean ± σ):     112.0 ms ±   5.9 ms    [User: 668.3 ms, System: 691.1 ms]
  Range (min … max):   105.2 ms … 126.2 ms    27 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -s  >/dev/null
  Time (mean ± σ):      1.339 s ±  0.017 s    [User: 2.004 s, System: 0.976 s]
  Range (min … max):    1.323 s …  1.384 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null ran
    1.15 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -s  >/dev/null
    1.30 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -s  >/dev/null
   11.96 ± 0.64 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -s  >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -r  >/dev/null
  Time (mean ± σ):     399.9 ms ±   1.8 ms    [User: 3574.3 ms, System: 699.0 ms]
  Range (min … max):   397.0 ms … 402.6 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -r  >/dev/null
  Time (mean ± σ):     324.7 ms ±   6.9 ms    [User: 4224.5 ms, System: 863.9 ms]
  Range (min … max):   318.1 ms … 339.8 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null
  Time (mean ± σ):     321.6 ms ±  10.4 ms    [User: 3890.8 ms, System: 722.9 ms]
  Range (min … max):   313.3 ms … 340.4 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -r  >/dev/null
  Time (mean ± σ):      1.376 s ±  0.007 s    [User: 4.775 s, System: 0.999 s]
  Range (min … max):    1.363 s …  1.388 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null ran
    1.01 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- sum -r  >/dev/null
    1.24 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- sum -r  >/dev/null
    4.28 ± 0.14 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- sum -r  >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum  >/dev/null
  Time (mean ± σ):     132.5 ms ±   1.7 ms    [User: 600.4 ms, System: 733.4 ms]
  Range (min … max):   129.1 ms … 135.4 ms    22 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum  >/dev/null
  Time (mean ± σ):     119.7 ms ±   2.5 ms    [User: 715.5 ms, System: 878.4 ms]
  Range (min … max):   116.3 ms … 127.3 ms    24 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null
 
  Warning:   Time (mean ± σ):     100.4 ms ±   4.3 ms    [User: 413.6 ms, System: 651.9 ms]
  Range (min … max):    95.1 ms … 112.6 ms    29 runs
Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum  >/dev/null
  Time (mean ± σ):      1.334 s ±  0.009 s    [User: 1.800 s, System: 1.016 s]
  Range (min … max):    1.320 s …  1.347 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null ran
    1.19 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum  >/dev/null
    1.32 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum  >/dev/null
   13.28 ± 0.57 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum  >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- b2sum  >/dev/null
  Time (mean ± σ):     378.3 ms ±   3.3 ms    [User: 3390.1 ms, System: 698.8 ms]
  Range (min … max):   373.0 ms … 382.8 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- b2sum  >/dev/null
  Time (mean ± σ):     356.9 ms ±  13.3 ms    [User: 5293.5 ms, System: 866.1 ms]
  Range (min … max):   339.9 ms … 375.6 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null
  Time (mean ± σ):     358.9 ms ±  13.2 ms    [User: 4781.6 ms, System: 717.9 ms]
  Range (min … max):   340.8 ms … 386.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- b2sum  >/dev/null
  Time (mean ± σ):      1.369 s ±  0.006 s    [User: 4.529 s, System: 1.016 s]
  Range (min … max):    1.361 s …  1.381 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- b2sum  >/dev/null ran
    1.01 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null
    1.06 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- b2sum  >/dev/null
    3.84 ± 0.14 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- b2sum  >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     920.0 ms ±   3.1 ms    [User: 9266.2 ms, System: 701.2 ms]
  Range (min … max):   915.0 ms … 926.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     904.3 ms ±  28.4 ms    [User: 15678.9 ms, System: 879.5 ms]
  Range (min … max):   864.8 ms … 943.3 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     962.5 ms ±  20.6 ms    [User: 15017.9 ms, System: 732.0 ms]
  Range (min … max):   948.4 ms … 1015.2 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum -a sm3  >/dev/null
  Time (mean ± σ):      1.561 s ±  0.013 s    [User: 10.491 s, System: 1.063 s]
  Range (min … max):    1.540 s …  1.582 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -- cksum -a sm3  >/dev/null ran
    1.02 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  forkrun -j - -- cksum -a sm3  >/dev/null
    1.06 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
    1.73 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f4 |  parallel -m -- cksum -a sm3  >/dev/null

-------------------------------- 262144 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha1sum  >/dev/null
  Time (mean ± σ):      1.170 s ±  0.004 s    [User: 11.853 s, System: 2.934 s]
  Range (min … max):    1.163 s …  1.175 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha1sum  >/dev/null
  Time (mean ± σ):      1.111 s ±  0.004 s    [User: 19.571 s, System: 3.695 s]
  Range (min … max):    1.104 s …  1.119 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null
  Time (mean ± σ):      1.069 s ±  0.023 s    [User: 18.438 s, System: 3.239 s]
  Range (min … max):    1.042 s …  1.104 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha1sum  >/dev/null
  Time (mean ± σ):      5.206 s ±  0.036 s    [User: 16.133 s, System: 3.877 s]
  Range (min … max):    5.169 s …  5.267 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null ran
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha1sum  >/dev/null
    1.09 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha1sum  >/dev/null
    4.87 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha1sum  >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha256sum  >/dev/null
  Time (mean ± σ):      2.081 s ±  0.006 s    [User: 23.328 s, System: 2.905 s]
  Range (min … max):    2.073 s …  2.092 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha256sum  >/dev/null
  Time (mean ± σ):      2.162 s ±  0.020 s    [User: 40.216 s, System: 3.546 s]
  Range (min … max):    2.146 s …  2.206 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
  Time (mean ± σ):      2.118 s ±  0.042 s    [User: 39.132 s, System: 3.110 s]
  Range (min … max):    2.055 s …  2.180 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha256sum  >/dev/null
  Time (mean ± σ):      5.563 s ±  0.109 s    [User: 27.824 s, System: 4.050 s]
  Range (min … max):    5.470 s …  5.762 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha256sum  >/dev/null ran
    1.02 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
    1.04 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha256sum  >/dev/null
    2.67 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha256sum  >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha512sum  >/dev/null
  Time (mean ± σ):      1.571 s ±  0.003 s    [User: 16.950 s, System: 2.937 s]
  Range (min … max):    1.564 s …  1.575 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha512sum  >/dev/null
  Time (mean ± σ):      1.580 s ±  0.018 s    [User: 29.304 s, System: 3.610 s]
  Range (min … max):    1.561 s …  1.619 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
  Time (mean ± σ):      1.525 s ±  0.027 s    [User: 28.165 s, System: 3.184 s]
  Range (min … max):    1.492 s …  1.573 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha512sum  >/dev/null
  Time (mean ± σ):      5.361 s ±  0.039 s    [User: 21.227 s, System: 4.015 s]
  Range (min … max):    5.304 s …  5.436 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha512sum  >/dev/null
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha512sum  >/dev/null
    3.51 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha512sum  >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha224sum  >/dev/null
  Time (mean ± σ):      2.075 s ±  0.004 s    [User: 23.270 s, System: 2.881 s]
  Range (min … max):    2.068 s …  2.082 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha224sum  >/dev/null
  Time (mean ± σ):      2.164 s ±  0.019 s    [User: 40.159 s, System: 3.516 s]
  Range (min … max):    2.147 s …  2.200 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
  Time (mean ± σ):      2.106 s ±  0.035 s    [User: 38.984 s, System: 3.107 s]
  Range (min … max):    2.061 s …  2.157 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha224sum  >/dev/null
  Time (mean ± σ):      5.550 s ±  0.045 s    [User: 27.764 s, System: 4.060 s]
  Range (min … max):    5.503 s …  5.656 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha224sum  >/dev/null ran
    1.01 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
    1.04 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha224sum  >/dev/null
    2.67 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha224sum  >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha384sum  >/dev/null
  Time (mean ± σ):      1.558 s ±  0.006 s    [User: 16.780 s, System: 2.909 s]
  Range (min … max):    1.550 s …  1.572 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha384sum  >/dev/null
  Time (mean ± σ):      1.569 s ±  0.019 s    [User: 28.851 s, System: 3.610 s]
  Range (min … max):    1.540 s …  1.597 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
  Time (mean ± σ):      1.516 s ±  0.032 s    [User: 27.749 s, System: 3.149 s]
  Range (min … max):    1.476 s …  1.562 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha384sum  >/dev/null
  Time (mean ± σ):      5.362 s ±  0.042 s    [User: 21.048 s, System: 4.020 s]
  Range (min … max):    5.288 s …  5.446 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null ran
    1.03 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sha384sum  >/dev/null
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sha384sum  >/dev/null
    3.54 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sha384sum  >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- md5sum  >/dev/null
  Time (mean ± σ):      1.469 s ±  0.004 s    [User: 15.592 s, System: 2.902 s]
  Range (min … max):    1.462 s …  1.476 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- md5sum  >/dev/null
  Time (mean ± σ):      1.171 s ±  0.004 s    [User: 18.754 s, System: 3.743 s]
  Range (min … max):    1.164 s …  1.177 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null
  Time (mean ± σ):      1.132 s ±  0.009 s    [User: 17.826 s, System: 3.286 s]
  Range (min … max):    1.123 s …  1.148 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- md5sum  >/dev/null
  Time (mean ± σ):      5.320 s ±  0.044 s    [User: 20.155 s, System: 3.916 s]
  Range (min … max):    5.265 s …  5.381 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null ran
    1.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- md5sum  >/dev/null
    1.30 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- md5sum  >/dev/null
    4.70 ± 0.05 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- md5sum  >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -s  >/dev/null
  Time (mean ± σ):     497.8 ms ±   2.1 ms    [User: 3322.7 ms, System: 2925.0 ms]
  Range (min … max):   493.9 ms … 501.3 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -s  >/dev/null
  Time (mean ± σ):     394.4 ms ±   2.9 ms    [User: 4297.5 ms, System: 3735.9 ms]
  Range (min … max):   392.0 ms … 401.9 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null
  Time (mean ± σ):     352.5 ms ±   5.5 ms    [User: 3111.3 ms, System: 3152.8 ms]
  Range (min … max):   347.3 ms … 364.8 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -s  >/dev/null
  Time (mean ± σ):      4.925 s ±  0.029 s    [User: 7.781 s, System: 3.643 s]
  Range (min … max):    4.884 s …  4.987 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null ran
    1.12 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -s  >/dev/null
    1.41 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -s  >/dev/null
   13.97 ± 0.23 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -s  >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -r  >/dev/null
  Time (mean ± σ):      1.484 s ±  0.003 s    [User: 15.837 s, System: 2.843 s]
  Range (min … max):    1.478 s …  1.489 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -r  >/dev/null
  Time (mean ± σ):      1.200 s ±  0.010 s    [User: 19.043 s, System: 3.557 s]
  Range (min … max):    1.190 s …  1.216 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null
  Time (mean ± σ):      1.152 s ±  0.014 s    [User: 18.047 s, System: 3.125 s]
  Range (min … max):    1.129 s …  1.179 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -r  >/dev/null
  Time (mean ± σ):      5.336 s ±  0.070 s    [User: 20.327 s, System: 3.859 s]
  Range (min … max):    5.229 s …  5.477 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null ran
    1.04 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- sum -r  >/dev/null
    1.29 ± 0.02 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- sum -r  >/dev/null
    4.63 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- sum -r  >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum  >/dev/null
  Time (mean ± σ):     441.6 ms ±   2.6 ms    [User: 2506.2 ms, System: 2982.5 ms]
  Range (min … max):   436.6 ms … 445.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum  >/dev/null
  Time (mean ± σ):     376.7 ms ±   3.7 ms    [User: 2943.0 ms, System: 3472.7 ms]
  Range (min … max):   369.9 ms … 382.0 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null
  Time (mean ± σ):     334.8 ms ±   2.2 ms    [User: 1768.7 ms, System: 2773.9 ms]
  Range (min … max):   330.9 ms … 338.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum  >/dev/null
  Time (mean ± σ):      4.879 s ±  0.029 s    [User: 6.914 s, System: 3.729 s]
  Range (min … max):    4.836 s …  4.936 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null ran
    1.13 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum  >/dev/null
    1.32 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum  >/dev/null
   14.57 ± 0.13 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum  >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- b2sum  >/dev/null
  Time (mean ± σ):      1.409 s ±  0.003 s    [User: 14.991 s, System: 2.824 s]
  Range (min … max):    1.403 s …  1.412 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- b2sum  >/dev/null
  Time (mean ± σ):      1.341 s ±  0.018 s    [User: 24.398 s, System: 3.562 s]
  Range (min … max):    1.324 s …  1.370 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null
  Time (mean ± σ):      1.299 s ±  0.007 s    [User: 23.243 s, System: 3.159 s]
  Range (min … max):    1.289 s …  1.311 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- b2sum  >/dev/null
  Time (mean ± σ):      5.283 s ±  0.038 s    [User: 19.180 s, System: 3.868 s]
  Range (min … max):    5.236 s …  5.354 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null ran
    1.03 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- b2sum  >/dev/null
    1.08 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- b2sum  >/dev/null
    4.07 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- b2sum  >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum -a sm3  >/dev/null
  Time (mean ± σ):      3.521 s ±  0.011 s    [User: 41.473 s, System: 2.874 s]
  Range (min … max):    3.510 s …  3.544 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum -a sm3  >/dev/null
  Time (mean ± σ):      3.998 s ±  0.051 s    [User: 76.700 s, System: 3.631 s]
  Range (min … max):    3.933 s …  4.107 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
  Time (mean ± σ):      3.941 s ±  0.050 s    [User: 75.203 s, System: 3.263 s]
  Range (min … max):    3.854 s …  4.005 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum -a sm3  >/dev/null
  Time (mean ± σ):      5.922 s ±  0.046 s    [User: 46.144 s, System: 4.139 s]
  Range (min … max):    5.838 s …  5.989 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -j - -- cksum -a sm3  >/dev/null ran
    1.12 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
    1.14 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  forkrun -- cksum -a sm3  >/dev/null
    1.68 ± 0.01 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f5 |  parallel -m -- cksum -a sm3  >/dev/null

-------------------------------- 586011 values --------------------------------


---------------- sha1sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha1sum  >/dev/null
  Time (mean ± σ):      2.731 s ±  0.268 s    [User: 23.494 s, System: 5.083 s]
  Range (min … max):    2.428 s …  3.192 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha1sum  >/dev/null
  Time (mean ± σ):      3.110 s ±  0.025 s    [User: 39.937 s, System: 7.662 s]
  Range (min … max):    3.081 s …  3.147 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null
  Time (mean ± σ):      2.984 s ±  0.045 s    [User: 35.422 s, System: 6.589 s]
  Range (min … max):    2.908 s …  3.053 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha1sum  >/dev/null
  Time (mean ± σ):     12.413 s ±  0.137 s    [User: 35.676 s, System: 8.504 s]
  Range (min … max):   12.237 s … 12.649 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha1sum  >/dev/null ran
    1.09 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha1sum  >/dev/null
    1.14 ± 0.11 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha1sum  >/dev/null
    4.55 ± 0.45 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha1sum  >/dev/null

---------------- sha256sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha256sum  >/dev/null
  Time (mean ± σ):      5.330 s ±  0.571 s    [User: 46.231 s, System: 5.151 s]
  Range (min … max):    4.105 s …  6.084 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha256sum  >/dev/null
  Time (mean ± σ):      6.207 s ±  0.074 s    [User: 80.918 s, System: 7.254 s]
  Range (min … max):    6.119 s …  6.377 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
  Time (mean ± σ):      5.925 s ±  0.050 s    [User: 72.237 s, System: 6.393 s]
  Range (min … max):    5.862 s …  6.018 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha256sum  >/dev/null
  Time (mean ± σ):     12.732 s ±  0.149 s    [User: 60.235 s, System: 8.711 s]
  Range (min … max):   12.598 s … 13.121 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha256sum  >/dev/null ran
    1.11 ± 0.12 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha256sum  >/dev/null
    1.16 ± 0.13 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha256sum  >/dev/null
    2.39 ± 0.26 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha256sum  >/dev/null

---------------- sha512sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha512sum  >/dev/null
  Time (mean ± σ):      3.800 s ±  0.244 s    [User: 34.624 s, System: 5.170 s]
  Range (min … max):    3.339 s …  4.184 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha512sum  >/dev/null
  Time (mean ± σ):      4.425 s ±  0.069 s    [User: 60.207 s, System: 7.425 s]
  Range (min … max):    4.378 s …  4.614 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
  Time (mean ± σ):      4.252 s ±  0.036 s    [User: 53.930 s, System: 6.494 s]
  Range (min … max):    4.195 s …  4.312 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha512sum  >/dev/null
  Time (mean ± σ):     12.684 s ±  0.228 s    [User: 46.582 s, System: 8.734 s]
  Range (min … max):   12.379 s … 13.048 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha512sum  >/dev/null ran
    1.12 ± 0.07 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha512sum  >/dev/null
    1.16 ± 0.08 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha512sum  >/dev/null
    3.34 ± 0.22 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha512sum  >/dev/null

---------------- sha224sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha224sum  >/dev/null
 
  Warning  Time (mean ± σ):      5.517 s ±  0.501 s    [User: 46.335 s, System: 5.011 s]
  Range (min … max):    4.480 s …  6.463 s    10 runs
: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha224sum  >/dev/null
  Time (mean ± σ):      6.190 s ±  0.088 s    [User: 80.673 s, System: 7.329 s]
  Range (min … max):    6.116 s …  6.428 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
  Time (mean ± σ):      5.916 s ±  0.061 s    [User: 71.831 s, System: 6.396 s]
  Range (min … max):    5.827 s …  6.019 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha224sum  >/dev/null
  Time (mean ± σ):     12.851 s ±  0.205 s    [User: 60.170 s, System: 8.753 s]
  Range (min … max):   12.586 s … 13.179 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha224sum  >/dev/null ran
    1.07 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha224sum  >/dev/null
    1.12 ± 0.10 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha224sum  >/dev/null
    2.33 ± 0.21 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha224sum  >/dev/null

---------------- sha384sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha384sum  >/dev/null
  Time (mean ± σ):      3.910 s ±  0.313 s    [User: 34.154 s, System: 5.040 s]
  Range (min … max):    3.368 s …  4.441 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha384sum  >/dev/null
  Time (mean ± σ):      4.380 s ±  0.025 s    [User: 58.712 s, System: 7.414 s]
  Range (min … max):    4.347 s …  4.416 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
  Time (mean ± σ):      4.205 s ±  0.058 s    [User: 52.649 s, System: 6.467 s]
  Range (min … max):    4.128 s …  4.322 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha384sum  >/dev/null
  Time (mean ± σ):     12.609 s ±  0.162 s    [User: 45.980 s, System: 8.767 s]
  Range (min … max):   12.413 s … 12.871 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sha384sum  >/dev/null ran
    1.08 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sha384sum  >/dev/null
    1.12 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sha384sum  >/dev/null
    3.22 ± 0.26 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sha384sum  >/dev/null

---------------- md5sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- md5sum  >/dev/null
 
    Time (mean ± σ):      3.474 s ±  0.202 s    [User: 27.317 s, System: 5.294 s]
  Range (min … max):    2.914 s …  3.657 s    10 runs
Warning: Statistical outliers were detected. Consider re-running this benchmark on a quiet system without any interferences from other programs.
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- md5sum  >/dev/null
  Time (mean ± σ):      3.576 s ±  0.015 s    [User: 39.589 s, System: 7.731 s]
  Range (min … max):    3.556 s …  3.604 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null
  Time (mean ± σ):      3.529 s ±  0.040 s    [User: 36.702 s, System: 6.716 s]
  Range (min … max):    3.498 s …  3.634 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- md5sum  >/dev/null
  Time (mean ± σ):     12.562 s ±  0.151 s    [User: 44.095 s, System: 8.621 s]
  Range (min … max):   12.381 s … 12.881 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- md5sum  >/dev/null ran
    1.02 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- md5sum  >/dev/null
    1.03 ± 0.06 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- md5sum  >/dev/null
    3.62 ± 0.22 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- md5sum  >/dev/null

---------------- sum -s ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -s  >/dev/null
  Time (mean ± σ):     942.0 ms ±  19.3 ms    [User: 6186.7 ms, System: 5077.1 ms]
  Range (min … max):   897.2 ms … 962.9 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -s  >/dev/null
  Time (mean ± σ):     868.7 ms ±   5.0 ms    [User: 9040.1 ms, System: 7380.5 ms]
  Range (min … max):   861.0 ms … 875.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null
  Time (mean ± σ):     844.8 ms ±  23.3 ms    [User: 6612.1 ms, System: 6424.7 ms]
  Range (min … max):   813.6 ms … 880.3 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -s  >/dev/null
  Time (mean ± σ):     11.702 s ±  0.248 s    [User: 17.600 s, System: 7.922 s]
  Range (min … max):   11.444 s … 12.290 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -s  >/dev/null ran
    1.03 ± 0.03 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -s  >/dev/null
    1.12 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -s  >/dev/null
   13.85 ± 0.48 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -s  >/dev/null

---------------- sum -r ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -r  >/dev/null
  Time (mean ± σ):      3.364 s ±  0.399 s    [User: 27.451 s, System: 5.187 s]
  Range (min … max):    2.784 s …  3.757 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -r  >/dev/null
  Time (mean ± σ):      3.684 s ±  0.033 s    [User: 40.211 s, System: 7.414 s]
  Range (min … max):    3.622 s …  3.716 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null
  Time (mean ± σ):      3.615 s ±  0.040 s    [User: 37.035 s, System: 6.501 s]
  Range (min … max):    3.576 s …  3.691 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -r  >/dev/null
 ⠋ Performing warmup runs         ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ ETA 00:00:00  Time (mean ± σ):     12.810 s ±  0.292 s    [User: 44.772 s, System: 8.546 s]
  Range (min … max):   12.469 s … 13.340 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- sum -r  >/dev/null ran
    1.07 ± 0.13 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- sum -r  >/dev/null
    1.10 ± 0.13 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- sum -r  >/dev/null
    3.81 ± 0.46 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- sum -r  >/dev/null

---------------- cksum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum  >/dev/null
  Time (mean ± σ):     838.5 ms ±  19.9 ms    [User: 4709.4 ms, System: 5352.6 ms]
  Range (min … max):   818.5 ms … 888.1 ms    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum  >/dev/null
  Time (mean ± σ):     809.0 ms ±  24.5 ms    [User: 6444.3 ms, System: 7395.9 ms]
  Range (min … max):   782.2 ms … 849.7 ms    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null
  Time (mean ± σ):     757.1 ms ±  19.0 ms    [User: 3947.7 ms, System: 6053.6 ms]
  Range (min … max):   726.0 ms … 777.0 ms    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum  >/dev/null
  Time (mean ± σ):     11.594 s ±  0.142 s    [User: 15.786 s, System: 8.011 s]
  Range (min … max):   11.419 s … 11.842 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum  >/dev/null ran
    1.07 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum  >/dev/null
    1.11 ± 0.04 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum  >/dev/null
   15.31 ± 0.43 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum  >/dev/null

---------------- b2sum ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- b2sum  >/dev/null
  Time (mean ± σ):      3.380 s ±  0.278 s    [User: 29.935 s, System: 4.939 s]
  Range (min … max):    2.809 s …  3.854 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- b2sum  >/dev/null
  Time (mean ± σ):      3.818 s ±  0.041 s    [User: 50.373 s, System: 7.419 s]
  Range (min … max):    3.759 s …  3.895 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null
  Time (mean ± σ):      3.657 s ±  0.046 s    [User: 45.610 s, System: 6.491 s]
  Range (min … max):    3.601 s …  3.756 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- b2sum  >/dev/null
  Time (mean ± σ):     12.747 s ±  0.263 s    [User: 42.319 s, System: 8.659 s]
  Range (min … max):   12.417 s … 13.150 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- b2sum  >/dev/null ran
    1.08 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- b2sum  >/dev/null
    1.13 ± 0.09 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- b2sum  >/dev/null
    3.77 ± 0.32 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- b2sum  >/dev/null

---------------- cksum -a sm3 ----------------

Benchmark 1: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum -a sm3  >/dev/null
  Time (mean ± σ):      9.418 s ±  1.315 s    [User: 84.287 s, System: 5.252 s]
  Range (min … max):    7.921 s … 11.723 s    10 runs
 
Benchmark 2: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     11.302 s ±  0.144 s    [User: 151.116 s, System: 7.593 s]
  Range (min … max):   11.168 s … 11.579 s    10 runs
 
Benchmark 3: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     10.887 s ±  0.159 s    [User: 135.324 s, System: 6.622 s]
  Range (min … max):   10.688 s … 11.135 s    10 runs
 
Benchmark 4: . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum -a sm3  >/dev/null
  Time (mean ± σ):     14.706 s ±  0.196 s    [User: 100.286 s, System: 9.275 s]
  Range (min … max):   14.518 s … 15.126 s    10 runs
 
Summary
  . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -j - -- cksum -a sm3  >/dev/null ran
    1.16 ± 0.16 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  xargs -P 28 -d $'\n' -- cksum -a sm3  >/dev/null
    1.20 ± 0.17 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  forkrun -- cksum -a sm3  >/dev/null
    1.56 ± 0.22 times faster than . /mnt/ramdisk/forkrun/forkrun.bash && cat "/mnt/ramdisk/hyperfine"/file_lists/f6 |  parallel -m -- cksum -a sm3  >/dev/null

-----------------------------------------------------
-------------------- "min" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0725523978    0.0721226738    0.0780041228    0.1975815078    0.1169567949    0.1160450899    0.1444382849    0.2621128129    0.0906708693    0.0899148883    0.1061667693    0.2243433423    0.1168318897    0.1160846677    0.1442157137    0.2612748527    0.0903507115    0.0898584395    0.1055139195    0.2239949925        0.0886244717    0.0878877677    0.1009041717    0.2197821947    0.0380075078    0.0371041448    0.0285186128    0.1735183368    0.0896882261    0.0885456301    0.1024201911    0.2212918341    0.0353699494    0.0353402484    0.0240484844    0.1730477044    0.0827196987    0.0817481547    0.09451803370.2125530707    0.1879997470    0.1860916360    0.2496539280    0.3637496960
4096    0.0657056338    0.0618684268    0.0583477448    0.2203571648    0.0940962594    0.0853919664    0.0968905324    0.2282287334    0.0798495342    0.0717726962    0.0768902462    0.2205532492    0.0951112377    0.0898550397    0.0964673447    0.2279548667    0.0789451473    0.0726989793    0.0758727263    0.2227307643        0.0758774239    0.0715698709    0.0713718689    0.2220737979    0.0434421315    0.0405070815    0.0301353205    0.2208299855    0.0767611398    0.0688831738    0.0716919398    0.2218488248    0.0415323502    0.0392811942    0.0267609932    0.2230407972    0.0743057733    0.0697865863    0.06996810530.2199667573    0.1414761990    0.1245226940    0.1571489720    0.2670710810
16384   0.1861064437    0.1818108027    0.2371538487    0.4699531817    0.3308593476    0.3321993356    0.4660064216    0.5508957056    0.2470166731    0.2437220611    0.3308402251    0.4992293851    0.3306529865    0.3312638225    0.4653589045    0.5500521885    0.2450103995    0.2420153525    0.3294799745    0.4992586515        0.2347715845    0.2336529045    0.3179754435    0.4950747455    0.0788641412    0.0721302292    0.0681296852    0.4484073182    0.2378455466    0.2370814026    0.3230080246    0.4979018506    0.0696360542    0.0641887052    0.0541575102    0.4459271822    0.2207783374    0.2166739014    0.29150666840.4854975134    0.5705968759    0.5710125149    0.8308316669    0.7696845009
65536   0.3149360966    0.2876817936    0.2714625426    1.3594634006    0.5471025163    0.5054047513    0.5448501583    1.4319339683    0.4180231937    0.3871492017    0.3957856647    1.3630993897    0.5430153130    0.4977255540    0.5490404090    1.4266507560    0.4124660904    0.3711873694    0.3875309644    1.3686946394        0.3948058887    0.3132724347    0.3156605927    1.3646928946    0.1444142048    0.1239236128    0.1052061858    1.3226337808    0.3970004378    0.3180793988    0.3132811618    1.3631187468    0.1291434844    0.1163467614    0.0951241184    1.3198329464    0.3730009485    0.3399208255    0.34075791451.3613860715    0.9150409836    0.8647716466    0.9483668306    1.5397971916
262144  1.1626626433    1.1040103783    1.0422668103    5.1691485993    2.0725882923    2.1456193263    2.0552970163    5.4700488813    1.5643724398    1.5605861988    1.4924364708    5.3043890328    2.0680748678    2.1470804858    2.0607509078    5.5027617108    1.5501270138    1.5402650878    1.4758862048    5.2878270958        1.4619552301    1.1638303721    1.1234364581    5.2650890001    0.4938620122    0.3919884812    0.3472970432    4.8839842472    1.4780230706    1.1897143886    1.1285152986    5.2285827766    0.4365862443    0.3699483163    0.3308791083    4.8364653673    1.4028930963    1.3236190393    1.28913633435.2357806003    3.5098147680    3.9333539610    3.8538450440    5.8380093620
586011  2.4276591146    3.0813019746    2.9077122496    12.236850208    4.1050336653    6.1186298383    5.8624424003    12.598378714    3.3388726601    4.3777187301    4.1948262391    12.378971906    4.4795807704    6.1157546074    5.8268564734    12.585955510    3.3677392950    4.3468153730    4.1279138520    12.413084845        2.9135893307    3.5561772957    3.4977309187    12.381161794    0.8972251668    0.8609553668    0.8136477188    11.443610320    2.7835685731    3.6223191071    3.5759843461    12.468762665    0.8184523984    0.7821965594    0.7260106253    11.418625359    2.8089349239    3.7590206639    3.601067244912.416593379    7.9210641796    11.167609870    10.687889756    14.517996637

-----------------------------------------------------
-------------------- "mean" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0729986337    0.0726438498    0.0786929481    0.1983686281    0.1178887940    0.1168175770    0.1450291328    0.2627680607    0.0915193727    0.0906166785    0.1069876558    0.2256129898    0.1179233142    0.1169606896    0.1452468845    0.2622281089    0.0912443234    0.0906186723    0.1063693690    0.2247533273        0.0890070625    0.0884801455    0.1017645610    0.2206284252    0.0382960702    0.0375444967    0.0290922474    0.1745926221    0.0903426233    0.0892278013    0.1029232827    0.2222339852    0.0357433844    0.0357441551    0.0247579751    0.1746654816    0.0837265595    0.0824956737    0.09508447950.2138713645    0.1889521545    0.1869790231    0.2506024359    0.3654057116
4096    0.0661840565    0.0631868848    0.0588007596    0.2228451395    0.0963305259    0.0916022730    0.0975863248    0.2299717529    0.0805619400    0.0760836137    0.0775900629    0.2237064444    0.0964376041    0.0913128407    0.0970756370    0.2291458685    0.0798627401    0.0753604621    0.0762725241    0.2250203377        0.0767487221    0.0736241318    0.0718950337    0.2238975304    0.0443827118    0.0418348287    0.0306547620    0.2226764882    0.0775690764    0.0734637581    0.0722305178    0.2228000943    0.0419115283    0.0398853250    0.0272001378    0.2253928006    0.0753628955    0.0714527820    0.07047995240.2231672891    0.1431032586    0.1343855719    0.1577156049    0.2682172314
16384   0.1867448324    0.1925256920    0.2380598133    0.4720129827    0.3323020804    0.3560673562    0.4670436510    0.5526478979    0.2476502682    0.2617813669    0.3317568490    0.5032501588    0.3317256776    0.3354305875    0.4668105777    0.5530403535    0.2456154572    0.2564123029    0.3300655347    0.5018619060        0.2364484285    0.2367402501    0.3187148050    0.4993174378    0.0813095412    0.0757867676    0.0686493961    0.4527389800    0.2395837506    0.2441211593    0.3246076297    0.5005592273    0.0723668135    0.0673458048    0.0547791618    0.4502455741    0.2220254651    0.2296233435    0.29204549370.4894031238    0.5719156242    0.6161902771    0.8339167203    0.7736273921
65536   0.3188421906    0.3115142043    0.2878229015    1.3675934002    0.5520720748    0.5269986288    0.5592056403    1.4373499917    0.4255231199    0.4094512303    0.4215202694    1.3790833710    0.5509315116    0.5322249734    0.5597241668    1.4509291245    0.4167700093    0.4037181702    0.4077169996    1.3762411358        0.3968155464    0.3218475585    0.3246737212    1.3788407814    0.1459912927    0.1285336372    0.1119777627    1.3393828703    0.3998616902    0.3247220793    0.3216046409    1.3761511865    0.1325361306    0.1196891365    0.1004428147    1.3338720147    0.3783354928    0.3568925008    0.35888725271.3690960464    0.9199953053    0.9042869251    0.9624711546    1.5613788132
262144  1.1704894673    1.1107065274    1.0691515146    5.2061041091    2.0810340363    2.1616866236    2.1178840759    5.5625584077    1.5712303390    1.5798046690    1.5253792051    5.3614981377    2.0751290002    2.1641202502    2.1061915334    5.5500684137    1.5583065970    1.5692982709    1.5158686253    5.3623526620        1.4693233844    1.1714122392    1.1320884441    5.3196362203    0.4978460815    0.3944127100    0.3524637986    4.9250502378    1.4836370908    1.1997874949    1.1520724553    5.3356571619    0.4416305560    0.3767219117    0.3348299146    4.8794891111    1.4090221802    1.3412780263    1.29908540525.2827356441    3.5213136030    3.9984402990    3.9412410380    5.9216898061
586011  2.7309507643    3.1103351893    2.9844935873    12.41332715,    5.3296147975    6.2072761468    5.9253972546    12.732141631    3.8004267249    4.4250068973    4.2521185436    12.684383937    5.5165028142    6.1900941278    5.9161201206    12.850889940    3.9101034133    4.3804403290    4.2047813118    12.609324899        3.4743035760    3.5756821862    3.5294740487    12.561923601    0.9420243471    0.8687112248    0.8448194670    11.702274584    3.3638542904    3.6839243243    3.6146365134    12.809750503    0.8385388131    0.808976395,    0.7571104232    11.593888609    3.3800159260    3.8179004181    3.656812842212.746551755    9.4178972840    11.301512421    10.886795613    14.706000345

-----------------------------------------------------
-------------------- "max" TIMES --------------------
-----------------------------------------------------

#       sha1sum         sha1sum         sha256sum       sha256sum       sha512sum       sha512sum       sha224sum       sha224sum       sha384sum       sha384sum       md5sum          md5sum          sum -s          sum -s          sum -r          sum -r          cksum           cksum           b2sum           b2sum       cksum -a sm     cksum -a sm    
(stdin) (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)     (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)      (forkrun)       (xargs)         (parallel)    

1024    0.0739321098    0.0739651528    0.0796730138    0.1994936218    0.1189131689    0.1181795919    0.1468145369    0.2641730919    0.0940295633    0.0916032143    0.1083504923    0.2278052833    0.1189054857    0.1177913787    0.1511062097    0.2630209587    0.0923420715    0.0918614835    0.1115000535    0.2258198825        0.0896880227    0.0893279817    0.1024441307    0.2216920027    0.0389146008    0.0382549688    0.0303230278    0.1766418428    0.0922992541    0.0903393361    0.1055418591    0.2233919971    0.0371319214    0.0364629264    0.0260736074    0.1769709324    0.0847171207    0.0836367067    0.09641275970.2151096877    0.1897622730    0.1877157250    0.2514241040    0.3741536640
4096    0.0671580348    0.0660309198    0.0597265498    0.2249078708    0.1032419434    0.0961502204    0.1001868774    0.2318666664    0.0830049082    0.0808818602    0.0788269062    0.2268564782    0.0996346617    0.0962510497    0.0978115867    0.2312865797    0.0821952103    0.0798418413    0.0770482163    0.2279198343        0.0785507019    0.0762811479    0.0727875169    0.2259007289    0.0449583315    0.0435116265    0.0312631035    0.2248262315    0.0799232148    0.0773124038    0.0732194268    0.2251965868    0.0429821402    0.0418754112    0.0283490262    0.2324397202    0.0771120113    0.0742315113    0.07193236030.2255962023    0.1468038510    0.1405883710    0.1624930040    0.2698297450
16384   0.1879870687    0.2084759197    0.2393882327    0.4748952537    0.3348178926    0.3857361966    0.4691192466    0.5553530456    0.2486845251    0.3032537681    0.3331968121    0.5064210891    0.3326965185    0.3447057805    0.4726430405    0.5581809925    0.2463392835    0.3008425735    0.3311317685    0.5097725175        0.2375729635    0.2459359375    0.3197576065    0.5093856255    0.0831484442    0.0879606432    0.0694665302    0.4693418282    0.2467133426    0.2640622166    0.3311217816    0.5057026936    0.0740357092    0.0778320452    0.0554745872    0.4601500622    0.2228933394    0.2494153294    0.29271935940.4942957204    0.5730660799    0.6499368279    0.8509370189    0.7944885339
65536   0.3216067336    0.3288479686    0.2990399696    1.3824535486    0.5667750123    0.5660700473    0.5943609783    1.4521840373    0.4342913217    0.4391632337    0.4419972977    1.3894636457    0.5595629410    0.5601899990    0.5790068060    1.4852046490    0.4218432274    0.4326274634    0.4327489014    1.3876841044        0.3991959717    0.3308525967    0.3397697177    1.4312059137    0.1478788508    0.1344573338    0.1262073288    1.3835160978    0.4025562228    0.3397682728    0.3404259058    1.3878042378    0.1354459294    0.1272928694    0.1126130524    1.3467787094    0.3828025605    0.3756098315    0.38631254351.3805319495    0.9260561486    0.9433126346    1.0151922336    1.5818055766
262144  1.1749689273    1.1191564943    1.1044494033    5.2669678363    2.0918011943    2.2059596923    2.1804185613    5.7620865763    1.5754954398    1.6186838808    1.5733106188    5.4356655968    2.0824864828    2.1996684088    2.1572498628    5.6560110178    1.5715729968    1.5974568878    1.5619048368    5.4459018158        1.4756155661    1.1773316031    1.1475531581    5.3813246691    0.5013093642    0.4018634162    0.3648344582    4.9873201852    1.4885417416    1.2161385966    1.1790109806    5.4767277616    0.4451385923    0.3819530213    0.3383308883    4.9355524123    1.4118805403    1.3699064333    1.31063228735.3537769673    3.5442428030    4.1068941330    4.0052213660    5.9891914210
586011  3.1919834585    3.1472444286    3.0530607595    12.648966998    6.0835506173    6.3770010673    6.0179197373    13.120678614    4.1841942521    4.6144037661    4.3115829351    13.048071987    6.4629960854    6.4282662054    6.0187979104    13.179427487    4.4414836180    4.4159255610    4.3216436270    12.870632942        3.6571411417    3.6039865047    3.6338961817    12.880684587    0.9629361368    0.8757187768    0.8802610278    12.290283507    3.7573387511    3.7161162761    3.6908904071    13.340296357    0.8881474584    0.8497263924    0.7769537884    11.841933563    3.8541737359    3.8947204259    3.756275856913.149657574    11.723271896    11.579391333    11.134529772    15.126076903


||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0729986337    0.0726438498    0.0786929481    0.1983686281    forkrun is 8.327% faster than xargs (1.0832x)   forkrun is 173.0% faster than parallel (2.7307x)
sha256sum       0.1178887940    0.1168175770    0.1450291328    0.2627680607    forkrun is 24.15% faster than xargs (1.2415x)   forkrun is 124.9% faster than parallel (2.2493x)
sha512sum       0.0915193727    0.0906166785    0.1069876558    0.2256129898    forkrun is 18.06% faster than xargs (1.1806x)   forkrun is 148.9% faster than parallel (2.4897x)
sha224sum       0.1179233142    0.1169606896    0.1452468845    0.2622281089    forkrun is 24.18% faster than xargs (1.2418x)   forkrun is 124.2% faster than parallel (2.2420x)
sha384sum       0.0912443234    0.0906186723    0.1063693690    0.2247533273    forkrun is 17.38% faster than xargs (1.1738x)   forkrun is 148.0% faster than parallel (2.4802x)
md5sum          0.0890070625    0.0884801455    0.1017645610    0.2206284252    forkrun is 15.01% faster than xargs (1.1501x)   forkrun is 149.3% faster than parallel (2.4935x)
sum -s          0.0382960702    0.0375444967    0.0290922474    0.1745926221    xargs is 29.05% faster than forkrun (1.2905x)   forkrun is 365.0% faster than parallel (4.6502x)
sum -r          0.0903426233    0.0892278013    0.1029232827    0.2222339852    forkrun is 15.34% faster than xargs (1.1534x)   forkrun is 149.0% faster than parallel (2.4906x)
cksum           0.0357433844    0.0357441551    0.0247579751    0.1746654816    xargs is 44.37% faster than forkrun (1.4437x)   forkrun is 388.6% faster than parallel (4.8866x)
b2sum           0.0837265595    0.0824956737    0.0950844795    0.2138713645    forkrun is 15.25% faster than xargs (1.1525x)   forkrun is 159.2% faster than parallel (2.5925x)
cksum -a sm3    0.1889521545    0.1869790231    0.2506024359    0.3654057116    forkrun is 34.02% faster than xargs (1.3402x)   forkrun is 95.42% faster than parallel (1.9542x)

OVERALL         1.0176422929    1.0081287630    1.1865509724    2.5451287054    forkrun is 17.69% faster than xargs (1.1769x)   forkrun is 152.4% faster than parallel (2.5246x)




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0661840565    0.0631868848    0.0588007596    0.2228451395    xargs is 7.459% faster than forkrun (1.0745x)   forkrun is 252.6% faster than parallel (3.5267x)
sha256sum       0.0963305259    0.0916022730    0.0975863248    0.2299717529    forkrun is 1.303% faster than xargs (1.0130x)   forkrun is 138.7% faster than parallel (2.3873x)
sha512sum       0.0805619400    0.0760836137    0.0775900629    0.2237064444    forkrun is 1.979% faster than xargs (1.0197x)   forkrun is 194.0% faster than parallel (2.9402x)
sha224sum       0.0964376041    0.0913128407    0.0970756370    0.2291458685    forkrun is 6.311% faster than xargs (1.0631x)   forkrun is 150.9% faster than parallel (2.5094x)
sha384sum       0.0798627401    0.0753604621    0.0762725241    0.2250203377    forkrun is 1.210% faster than xargs (1.0121x)   forkrun is 198.5% faster than parallel (2.9859x)
md5sum          0.0767487221    0.0736241318    0.0718950337    0.2238975304    xargs is 2.405% faster than forkrun (1.0240x)   forkrun is 204.1% faster than parallel (3.0410x)
sum -s          0.0443827118    0.0418348287    0.0306547620    0.2226764882    xargs is 36.47% faster than forkrun (1.3647x)   forkrun is 432.2% faster than parallel (5.3227x)
sum -r          0.0775690764    0.0734637581    0.0722305178    0.2228000943    xargs is 1.707% faster than forkrun (1.0170x)   forkrun is 203.2% faster than parallel (3.0327x)
cksum           0.0419115283    0.0398853250    0.0272001378    0.2253928006    xargs is 46.63% faster than forkrun (1.4663x)   forkrun is 465.1% faster than parallel (5.6510x)
b2sum           0.0753628955    0.0714527820    0.0704799524    0.2231672891    xargs is 1.380% faster than forkrun (1.0138x)   forkrun is 212.3% faster than parallel (3.1232x)
cksum -a sm3    0.1431032586    0.1343855719    0.1577156049    0.2682172314    forkrun is 17.36% faster than xargs (1.1736x)   forkrun is 99.58% faster than parallel (1.9958x)

OVERALL         .87845505997    .83219247238    .83750131755    2.5168409776    forkrun is .6379% faster than xargs (1.0063x)   forkrun is 202.4% faster than parallel (3.0243x)




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.1867448324    0.1925256920    0.2380598133    0.4720129827    forkrun is 23.65% faster than xargs (1.2365x)   forkrun is 145.1% faster than parallel (2.4516x)
sha256sum       0.3323020804    0.3560673562    0.4670436510    0.5526478979    forkrun is 40.54% faster than xargs (1.4054x)   forkrun is 66.30% faster than parallel (1.6630x)
sha512sum       0.2476502682    0.2617813669    0.3317568490    0.5032501588    forkrun is 33.96% faster than xargs (1.3396x)   forkrun is 103.2% faster than parallel (2.0321x)
sha224sum       0.3317256776    0.3354305875    0.4668105777    0.5530403535    forkrun is 40.72% faster than xargs (1.4072x)   forkrun is 66.71% faster than parallel (1.6671x)
sha384sum       0.2456154572    0.2564123029    0.3300655347    0.5018619060    forkrun is 34.38% faster than xargs (1.3438x)   forkrun is 104.3% faster than parallel (2.0432x)
md5sum          0.2364484285    0.2367402501    0.3187148050    0.4993174378    forkrun is 34.79% faster than xargs (1.3479x)   forkrun is 111.1% faster than parallel (2.1117x)
sum -s          0.0813095412    0.0757867676    0.0686493961    0.4527389800    xargs is 10.39% faster than forkrun (1.1039x)   forkrun is 497.3% faster than parallel (5.9738x)
sum -r          0.2395837506    0.2441211593    0.3246076297    0.5005592273    forkrun is 32.96% faster than xargs (1.3296x)   forkrun is 105.0% faster than parallel (2.0504x)
cksum           0.0723668135    0.0673458048    0.0547791618    0.4502455741    xargs is 22.94% faster than forkrun (1.2294x)   forkrun is 568.5% faster than parallel (6.6855x)
b2sum           0.2220254651    0.2296233435    0.2920454937    0.4894031238    forkrun is 31.53% faster than xargs (1.3153x)   forkrun is 120.4% faster than parallel (2.2042x)
cksum -a sm3    0.5719156242    0.6161902771    0.8339167203    0.7736273921    forkrun is 45.81% faster than xargs (1.4581x)   forkrun is 35.26% faster than parallel (1.3526x)

OVERALL         2.7676879395    2.8720249084    3.7264496329    5.7487050346    forkrun is 34.64% faster than xargs (1.3464x)   forkrun is 107.7% faster than parallel (2.0770x)




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.3188421906    0.3115142043    0.2878229015    1.3675934002    xargs is 8.231% faster than forkrun (1.0823x)   forkrun is 339.0% faster than parallel (4.3901x)
sha256sum       0.5520720748    0.5269986288    0.5592056403    1.4373499917    forkrun is 6.111% faster than xargs (1.0611x)   forkrun is 172.7% faster than parallel (2.7274x)
sha512sum       0.4255231199    0.4094512303    0.4215202694    1.3790833710    xargs is .9496% faster than forkrun (1.0094x)   forkrun is 224.0% faster than parallel (3.2409x)
sha224sum       0.5509315116    0.5322249734    0.5597241668    1.4509291245    forkrun is 5.166% faster than xargs (1.0516x)   forkrun is 172.6% faster than parallel (2.7261x)
sha384sum       0.4167700093    0.4037181702    0.4077169996    1.3762411358    xargs is 2.220% faster than forkrun (1.0222x)   forkrun is 230.2% faster than parallel (3.3021x)
md5sum          0.3968155464    0.3218475585    0.3246737212    1.3788407814    forkrun is .8781% faster than xargs (1.0087x)   forkrun is 328.4% faster than parallel (4.2841x)
sum -s          0.1459912927    0.1285336372    0.1119777627    1.3393828703    xargs is 14.78% faster than forkrun (1.1478x)   forkrun is 942.0% faster than parallel (10.420x)
sum -r          0.3998616902    0.3247220793    0.3216046409    1.3761511865    xargs is 24.33% faster than forkrun (1.2433x)   forkrun is 244.1% faster than parallel (3.4415x)
cksum           0.1325361306    0.1196891365    0.1004428147    1.3338720147    xargs is 19.16% faster than forkrun (1.1916x)   forkrun is 1014.% faster than parallel (11.144x)
b2sum           0.3783354928    0.3568925008    0.3588872527    1.3690960464    forkrun is .5589% faster than xargs (1.0055x)   forkrun is 283.6% faster than parallel (3.8361x)
cksum -a sm3    0.9199953053    0.9042869251    0.9624711546    1.5613788132    forkrun is 6.434% faster than xargs (1.0643x)   forkrun is 72.66% faster than parallel (1.7266x)

OVERALL         4.6376743646    4.3398790449    4.4160473249    15.369918736    forkrun is 1.755% faster than xargs (1.0175x)   forkrun is 254.1% faster than parallel (3.5415x)




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         1.1704894673    1.1107065274    1.0691515146    5.2061041091    xargs is 3.886% faster than forkrun (1.0388x)   forkrun is 368.7% faster than parallel (4.6872x)
sha256sum       2.0810340363    2.1616866236    2.1178840759    5.5625584077    forkrun is 1.770% faster than xargs (1.0177x)   forkrun is 167.2% faster than parallel (2.6729x)
sha512sum       1.5712303390    1.5798046690    1.5253792051    5.3614981377    xargs is 3.005% faster than forkrun (1.0300x)   forkrun is 241.2% faster than parallel (3.4122x)
sha224sum       2.0751290002    2.1641202502    2.1061915334    5.5500684137    forkrun is 1.496% faster than xargs (1.0149x)   forkrun is 167.4% faster than parallel (2.6745x)
sha384sum       1.5583065970    1.5692982709    1.5158686253    5.3623526620    xargs is 2.799% faster than forkrun (1.0279x)   forkrun is 244.1% faster than parallel (3.4411x)
md5sum          1.4693233844    1.1714122392    1.1320884441    5.3196362203    xargs is 3.473% faster than forkrun (1.0347x)   forkrun is 354.1% faster than parallel (4.5412x)
sum -s          0.4978460815    0.3944127100    0.3524637986    4.9250502378    xargs is 11.90% faster than forkrun (1.1190x)   forkrun is 1148.% faster than parallel (12.487x)
sum -r          1.4836370908    1.1997874949    1.1520724553    5.3356571619    xargs is 4.141% faster than forkrun (1.0414x)   forkrun is 344.7% faster than parallel (4.4471x)
cksum           0.4416305560    0.3767219117    0.3348299146    4.8794891111    xargs is 12.51% faster than forkrun (1.1251x)   forkrun is 1195.% faster than parallel (12.952x)
b2sum           1.4090221802    1.3412780263    1.2990854052    5.2827356441    xargs is 3.247% faster than forkrun (1.0324x)   forkrun is 293.8% faster than parallel (3.9385x)
cksum -a sm3    3.5213136030    3.9984402990    3.9412410380    5.9216898061    xargs is 1.451% faster than forkrun (1.0145x)   forkrun is 48.09% faster than parallel (1.4809x)

OVERALL         17.278962336    17.067669022    16.546256010    58.706839911    xargs is 3.151% faster than forkrun (1.0315x)   forkrun is 243.9% faster than parallel (3.4396x)




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         2.7309507643    3.1103351893    2.9844935873    12.41332715     forkrun is 9.284% faster than xargs (1.0928x)   forkrun is 354.5% faster than parallel (4.5454x)
sha256sum       5.3296147975    6.2072761468    5.9253972546    12.732141631    forkrun is 11.17% faster than xargs (1.1117x)   forkrun is 138.8% faster than parallel (2.3889x)
sha512sum       3.8004267249    4.4250068973    4.2521185436    12.684383937    forkrun is 11.88% faster than xargs (1.1188x)   forkrun is 233.7% faster than parallel (3.3376x)
sha224sum       5.5165028142    6.1900941278    5.9161201206    12.850889940    forkrun is 7.244% faster than xargs (1.0724x)   forkrun is 132.9% faster than parallel (2.3295x)
sha384sum       3.9101034133    4.3804403290    4.2047813118    12.609324899    forkrun is 7.536% faster than xargs (1.0753x)   forkrun is 222.4% faster than parallel (3.2248x)
md5sum          3.4743035760    3.5756821862    3.5294740487    12.561923601    forkrun is 1.587% faster than xargs (1.0158x)   forkrun is 261.5% faster than parallel (3.6156x)
sum -s          0.9420243471    0.8687112248    0.8448194670    11.702274584    xargs is 11.50% faster than forkrun (1.1150x)   forkrun is 1142.% faster than parallel (12.422x)
sum -r          3.3638542904    3.6839243243    3.6146365134    12.809750503    forkrun is 7.455% faster than xargs (1.0745x)   forkrun is 280.8% faster than parallel (3.8080x)
cksum           0.8385388131    0.808976395     0.7571104232    11.593888609    xargs is 6.850% faster than forkrun (1.0685x)   forkrun is 1333.% faster than parallel (14.331x)
b2sum           3.3800159260    3.8179004181    3.6568128422    12.746551755    forkrun is 8.189% faster than xargs (1.0818x)   forkrun is 277.1% faster than parallel (3.7711x)
cksum -a sm3    9.4178972840    11.301512421    10.886795613    14.706000345    forkrun is 15.59% faster than xargs (1.1559x)   forkrun is 56.14% faster than parallel (1.5614x)

OVERALL         42.704232751    48.369859660    46.572559726    139.41045695    forkrun is 9.058% faster than xargs (1.0905x)   forkrun is 226.4% faster than parallel (3.2645x)
```
