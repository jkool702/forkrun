I ran many hours worth of benchmarking/speedtests to compare the performance of `forkrun`, `xargs` and `parallel` under various scenarios. Benchmarking was done using [hyperfine](https://github.com/sharkdp/hyperfine).

The hyperfine-based speedtest/benchmarktest code can be found in the `forkrun.speedtest.hyperfine.bash` file, and the results (compiled into large-but-usefu tables) can be found in the `RESULTS.md` file. Some descriptions about the benchmark and observations regarding the results are shown below. 

## DESCRIPTION OF BENCHMARK

This benchmark computes 11 different checksums on various-sie batches of small files using `hyperfine`. Hyperfine takes care of properly running the benchmark to ensure accurate results,including things like "setting up a fresh shell" and "masking the programs outout so it isnt waiting to write to the terminal". Additionally, for each individual benchmark time, hyperfine runs the function at least 11 times (1 warmup run + at least 10timing runs). The faster running benchmarks (less than a couple hundred ms) are run more than 10 times (the fastest ones that were only a few ms were run several hundred times).

In total 1188 hyperfine benchmarks were run, representing every combination of:

* 3 parallelization codes
* 11 checksums codes
* 6 batch sizes
* 2 input styes
* 3 output styles

***

3 parallelization codes were tested and timed:

* `forkrun`
* `xargs -P $(nproc) -d $'\n'`
* `parallel -m`

Each of these parallelization codes copmputed 11 different checksums on various-sized batches of files:

* `sha1sum`
* `sha256sum`
* `sha512sum`
* `sha224sum`
* `sha384sum`
* `md5sum `
* `sum -s`
* `sum -r`
* `cksum`
* `b2sum`
* `cksum -a sm3`

Batches of computing these checksums on:

* 10 files
* 100 files
* 1,000 file
* 10,000 files
* 100,000 files 
* ~520,000 files 

were tested for each parallelization code + checksum checksum combination. 

NOTE: in the `RESULTS.md` file, each "table" of results shows the execution time for each of the above 198 (3x11x6) combinationn, and for each of the 66 (11x6) checksum + total batch size combinations gives the relative performance between "forkrun vs. xargs" and "forkrun va parallel".

Additionallly, each parallelization code + checksum + total batch size combination was tested with 2 different data input styles:

* `<cmd> <file`       (LABEL: INPUT FROM FILE)
* `cat file | <cmd>`  (LABEL: INPUT FROM PIPE)

as well as 3 different output styles:

* `<cmd>  # (to stdout)`  (LABEL: OUTPUT TO STDOUT)
* `<cmd> | wc -l`         (LABEL: OUTPUT TO PIPE)
* `<cmd> >/dev/null`      (LABEL: OUTPUT TO REDIRECT)

These 6 (2x3) input/output style combinations are each shown in their own seperate table in the `RESULTS.md` file and are identified using the LABEL's listed above.

# TRENDS IN THE RESULTS

BRIEF SUMMARY: For total execution time less than 50 ms `xargs` was the fastest. For total execution time more than 50 ms `forkrun` was the fastest. `parallel` was never the fastest.

The parameter (excluding parallelization code used) that seemed to have to strongest effect on the relative performance of `forkrun`, `xargs` and `parallel` seemed to be the total batch size (i.e., the total number of file checksums computed). For very low (10+100 files) total batch sizes `xargs` was the faster than `forkrun`, which was faster than `parallel`. This is because `xargs` has the lowest base "no-load" time (i.e., the overhead from calling it with no inputs) and `parallel` has the highest base "no-load" time. (See below in "observations" for more info). At 1,000 inputs `forkrun` and `xargs` had about equal performance. A total execution time of ~50 ms seems to be about where the tipping point is: under 50 ms `xargs` is faster, over 50 ms `forkrun` is faster. At 10,000 inputs and 100,000 inputs `forkrun` is ~2x as fast as `xargs` and 2-4x as fast as `parallel`. At ~520,000 inputs `xargs` actually improves and starts to approach `forkrun`'s speed (though it is still always slightly slower). On the other hand, `parallel` gets worse and is on average nearly an order of magnitude slower than `forkrun` or `xargs`.

## OBSERVATIONS:

**BASE "NO-LOAD" TIME**: ~ 2ms for `xargs`; ~22 ms for `forkrun`; and ~163 ms for `parallel` --> `xargs` is fastest in cases where this is a significant part of the total runtime (i.e., problems that finish running very fast, say, for total run times of under 80 ms for `forkrun` and under 500 ms for `parallel`)

**FORKRUN vs XARGS**: `xargs` is faster for problems that take ~50-70 ms or less (due to lower "no-load" time. `forkrun` is faster for all problems that take longer than ~50-70 ms (which is most of the problems you'd actually want to parallelize). For medium-sized problems `forkrun` is typically around 75% faster. For larger problems (i.e., >>100k inputs) `forkrun` is typically around 25% faster. This suggests that `forkrun` is better at "ramping up to full speed" (i.e., its dynamic batch size logic gets up to the maximum batch size faster).\*\*

**FORKRUN vs PARALLEL**: In all cases forkrun was faster than parallel. Its best (relative) performance was for medium-sized problems (~10000 inputs), where its speed was comparable to `xargs` (and on occasion slightly faster even), but `forkrun` was still ~75% faster. For larger problems (cases where stdin had 100,000+ inputs), parallel's time is almost linearly dependent on the number of inputs and the checksum being used has minimal effect on the time taken, indicating that its maximum throughput is only about 1/10th of `forkrun`/`xargs` for larger problems with many inputs (each of which runs very quickly).

\*\*This is because forkrun tries to estimate how many "cached in a tmpfile but not yet processed" lines from stdin are available, divides by the number of worker coprocs and sets that (or the pre-set maximum, whichever is lower) as the batch size. The process that caches stdin to a tmpfile is forked off a good bit before the coproc workers are forked, so when all of stdin is available immediately the batch size goes up to maximum almost instantly. xargs, on the other hand, AFAIK, just gradually ramps up the batch size until it hits some pre-set maximum without considering how many unprocessed lines from stdin are available.

![image](https://github.com/user-attachments/assets/688deb4b-ed5a-4b74-868a-08644b789adb)
