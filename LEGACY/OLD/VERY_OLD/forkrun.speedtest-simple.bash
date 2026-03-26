time find /usr -type f | parallel -m -j$(nproc) sha256sum 2>/dev/null | wc -l

#346974
#
#real    0m9.889s
#user    0m40.019s
#sys     0m18.251s


time find /usr -type f -print0 | xargs -P$(nproc) -0 -- sha256sum 2>/dev/null | wc -l

#346974
#
#real    0m7.420s
#user    0m40.293s
#sys     0m18.135s


time find /usr -type f | forkrun  -- sha256sum 2>/dev/null | wc -l

#346974
#
#real    0m4.472s
#user    0m51.207s
#sys     0m22.038s
