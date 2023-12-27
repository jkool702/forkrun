# FORKRUN

`forkrun` is a pure-bash function for parallelizing loops in much the same way that `xargs` or `parallel` does, only faster than either (especially parallel).  In my testing, `forkrun` was, on average (for problems where the efficiency of the parallelization framework acvtually makes a difference) ~70% faster than `xargs -P $(nproc)` and ~7x as fast as `parallel -m -j $(nproc)`. See To be clear, these are the "fast" invocations of xargs and parallel. If you were to compare the "1 line at a time" version of all 3 (`forkrun -l1`, `xargs -P $(nproc) -L 1`, `parallel -j $(nprooc)`), `forkrun` is 7-10x as fast as `xargs` and 20-30x as fast as `parallel`.

***

# USAGE

`forkrun` in invoked in much the same way as `xargs`: on the command-line, pass forkrun options, then the functionscript/binary that you are parallelizing, then any initial constant arguments (in that order). The arguments to parallelize running are passed to forkrun on stdin. A typical `forkrun` invocation looks something like this:

    printf '%s\n' "${inArgs[@]}" | forkrun [flags] [--] parFunc ["${initialArgs[@]}"]

`forkrun` strives to automatically choose reasonable and near-optimal values for flags, so in most usage scenarios no flags will need to be set to attain maximum performance and speed.

NOTE: you'll need to `source` forkrun before using it

    source /path/to/forkrun.bash
    
Alternately, if you dont have `forkrun.bash` saved locally but have internet access (or want to ensure you are using the latest version), you can run
    
    source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)

***

**HELP**: the `forkrun.bash` script, when sourced, will source a helkper function (`forkrun_displayHelp`) to display help. This is activated by calling one of the following:

```
--usage              :  display brief usage info (shown above)
-? | -h | --help     :  dispay standard help (does not include detailed info on flags)
--help=s[hort]       :  more detailed varient of '--usage'
--help=f[lags]       :  display detailed info about flags
--help=a[ll]         :  display all help (including detailed flag info)
```

NOTE: text inside of the brackate `[...]` is optional.
NOTE: `forkrun -?` may not work unless you escape the `?`. i.e., `forkrun -\?` or `forkrun '-?'`

***
    
# HOW IT WORKS

**BASH COPROCS**: `forkrun` parallelizes loops by running multiple inputs through a script/function in parallel using bash coprocs. `forkrun` is fundementally different than most existing loop parallelization codes in the sense that individual function evaluations are not forked. Rather, initially a number of persistent bash coprocs are forked, and then inputs (passed on stdin) are distributed to these coprocs without any additional forking (or reopening pipes/fd's, or...). This,  combined with the (when possible) exclusive use of bash builtins (all of main loop, most of the rest of the code) (these avoid subshell generation, and their associated increase in execution time). This (as well as being *heavily* optimized) is what makes `forkrun` so fast. 

***

**AUTOMATIC BATCH SIZE ADJUSTMENT**: by default, `forkrun` will automatically dynamically adjust how many lines are passed to the function each time it is called (batch size). The batch size starts at 1, and is dynamically adjusted upwards (but never downwards) up to a maximum of 512 lines per batch (which is typically near-optimal in my personal trial-and-error testing). The logic used here involves:

1. Calculating the average bytes/line by looking number of lines read and number of bytes read (from `/proc/self/fdinfo/$fd`)
2. Estimating the number of remaining lines left to read by getting the difference in number of bytes read/written and dividing by the average bytes/line
3. dividing the estimatedd number of remaining lines by the number of worker coprocs

NOTE: this is a "maximum lines per batch" (implemented via `mapfile -n ${nLines}`)...if stdin is arriving slowly then fewer than this many lines will be used. What this serves to accomplish is to prevent a couple of coproc workers from claiming all the lines of input while the rest sit idle if the total number of lines is less than `512 * (# worker coprocs)`

To overrule this logic and set a static batch size use the '-l' flag. Alternately, use the `-L` flag to keep the auitomatic batch size logic enabled but to change the initial and maximum number of lines per batch.

***

**IPC**: Forkrun distributes stdin to the worker coprocs by first saving them to a tmpfile (by default on a tmpfs - under `/dev/shm`, customizable with the `-t` flag) using a forked coproc. The worker coprocs then read data from this file into an array (using `mapfile`) using a shared read-only file descriptor and an exclusive read lock. 

***

**NO FUNCTION MODE**: forkrun supports an additional mode of operation where `parFunc` and `initialArgs` are not given as function inputs, but instead are integrated into each line of `args`. In this mode, each line passed on stin will be run as-is (by saving groups of 512 lines to tmp files and then sourcing them). This allows you to easily run multiple different functions/scripts/binaries in paralel and still utalize forkrun's very quick and efficient parallelization method. To activate this mode, use flag `-N` and do not provide `parFunc` or `initialArgs`. This is implemented via `source <(printf '%s\n' "${args[@]}")`

***

# DEPENDENCIES

`forkrun` strives to rely on as few external dependencies as possible. 

***

**REQUIRED DEPENDENCIES**

Bash 4+ :             This is when coprocs were added. NOTE: `forkrun` will be much faster on bash 5.1+, since it healivy relies of arrays and the `mapfile` command which got a major overhaul in bash 5.1. The vast majority of testing has been done on bash 5.2 so while bash 4-5.0 *should* work it is not well tested.

`rm` and `mkdir`:     For basic filesystem operations that I couldnt figure out how to re-implement in pure bash. Either the GNU or the busybox versions of these will both work.

***

**OPTIONAL DEPENDENCIES**

Bash 5.1+:           For improved speed due to overhauled handling of arrays.

`mktemp` and `cat`:  The code will provide pure-bash replacements for these if they arent available, but if external binaries for these are present they will be used

`inotifywait`:       If available, this is used to monitor the tmpfile where stdin is saved before being read by the coprocs. This enables the coprocs to efficiently wait for input if stdin is arriving slowly (e.g., `ping 1.1.1.1 | forkrun <...>`)

`fallocate`:         If available, this is used to deallocate already-processed data from the beginning of the tmpfile holding stdin. This enables `forkrun` to be used in long-ruinning processes that consistently output data for days/weeks/months/... Without `fallocate`, this tmpfile will continually grow and will not be removed until forkrun exits 

***

# WHY USE FORKRUN

There are 2 other common programs for parallelizing loops in the (bash) shell: `xargs` and `parallel`. I believe `forkrun` offers more than either of these programs can offer:

***

**COMPARED TO PARALLEL**

* `forkrun` is considerably faster. In terms of "wall clock time" in my tests where I coimputed 11 different checksums of ~500,000 small files totaling ~19 gb saved on a ramdisk(see `forkrun.speedtest.bash` for details):
  * forkrun was on average 7x faster than `parallel -m`.
  * In the particuarly lightweight checksums (`sum -s`, `cksum`) `forkrun` was ~18x faster than `parallel -m`.
  * If comparing in "1 line at a time mode", forkrun is more like 20-30x faster.
  * In terms of "CPU" time forkrun also tended to use less CPU cycles thasn parallel, though the difference here is smaller (forkrun is very good at fully utalizing all CPU cores, but doesnt magically make running whaytever is being parallelized take fewer CPU cycles than running it sequential;ly would have taken).
* `forkrun` has fewer dependencies. As long as your system has a recent-ish version of bash (which is preinstalled on basically every non-embedded linux system) it can run `forkrun`. `parallel`, on the other hand, is not typically installed by default.

***

**COMPARED TO XARGS**

* Better set of available options. All of the `xargs` options (excluding those intended for running code interactively) have been implemented in `forkrun`. Additionally, a handful of additional (and rather useful) options have also been implemented. This includes:
  * ordering the output the same as the input (making it much easier to use forkrun as a filter)
  * passing stdin to the workers via the worker's stdin (`func <<<"${args[@]}"` instead of `func "${args[@]}"`)
  * a "no function mode" that allows you to embed the code to run into `"${args[@]}"` and run arbitrary code that differs from oline to line in parallel
  * The ability to unescape (via the `-u` flag) the input and have the commands run by `forkrun` interpret things like redirects and forks. (this *might* be possible in `xargs` by wrapping everything in a `bash -c` call, but that is unnecessary here).
  * Better/easier (IMO) usage of the `-i` flag to replace `{}` with the lines from stdin. No need to wrap everything in a `bash -c '...' _` call, and the `{}` can bne used multiple times.

* Because `forkrun` runs directly in the shell, other shell functions can be used as the `parFunc` being parallelized (this *might* be possible in `xargs` by exporting thje function first, but this is not needed with `forkrun`)

***

# SUPPORTED OPTIONS / FLAGS 

`forkrun` supports many of the same flags as `xargs` (with the exception of options intended for interactive use), plus several additional options that are present in `parallel` but not `xargs`. A quick summary will be provided here - for more info refer to the comment block at the top of the forkrun function, or source forkrun and then run `forkrun --help[=all]`. The following flags are supported:

**FLAGS WITH ARGUMENTS**

```
    (-j|-p) <#> : num worker coprocs. set number of worker coprocs. Default is $(nproc).
    -l <#>      : num lines per function call (batch size). set static number of lines to pass to the function on each function call. Disables automatic dynbamic batch size adjustment. if -l=1 then the "read from a pipe" mode (-p) flag is automatically activated (disable with flag `+p`)
    -L <#[,#]>  : set initial (<#>) or initial+maximum (<#,#>) lines per batch while keeping the automatic batch size adjustment enabled
    -t <path>   : set tmp directoiry. set the directory where the temp files containing lines from stdin will be kept (when -l != 1). These files will be saved inside a new mktemp-generated     -d <delimiter>: set the delimiter to something other than a newline (default) or NULL ((-z|-0) flag)
```

**FLAGS WITHOUT ARGUMENTS**: for each of these passing `-<FLAG>` enables the feasture, and passing `+<FLAG>` disables the feature. Unless othjerwise noted, all features are, by default, disabled. If a given flag is passed multiple times both enabling `-<FLAG>` and disabling `+<FLAG>` some option, the last one passed is used.

```
    -i          : insert {}. replace `{}` with the inputs passed on stdin (instead of placing them at the end)
    -I          : insert {id}. replace `{id}` with an index (0, 1, ...) describing which coproc the process ran on. 
    -k          : ordered output. retain input order in output. The 1st output will correspond to the 1st input, 2nd output to 2nd input, etc. Note: ordering is "close but not guaranteed" if flag -l=1 is also given (see '-ks'). Ordering guaranteed for -l>1.
    -n          : add ordering info to output. pre-pend each output group with an index describing its input order, demoted via `$'\n'\n$'\034'$INDEX$'\035'$'\n'`. This requires and will automatically enable the `-k` output ordering flag.
directory created under the directory specified here. Default is '/tmp'.
    (-0|-z)     : NULL-seperated stdin. stdin is NULL-separated, not newline separated.
    -s          : subshell. run each evaluation of `parFunc` in a subshell. This adds some overhead but ensures that running `parFunc` does not alter the coproc's environment and effect future evaluations of `parFunc`.
    -S          : pass via function's stdin. pass stdin to the function being parallelized via stdin ( $parFunc < /tmpdir/fileWithLinesFromStdin ) instead of via function inputs  ( $parFunc $(</tmpdir/fileWithLinesFromStdin) )
    -p          : pipe read. dont use a tmpfile and have coprocs read (via shared file descriptor) directly from stdin. Enabled by default only when `-l 1` is passed.
    -D          : delete tmpdir. Remove the tmp dir used by `forkrun` when `forkrun` exits. NOTE: the `-D` flag is enabled by default...disable with flag `+D`.
    -N          : enable no func mode. Only has an effect when `parFunc` and `initialArgs` were not given. If `-N` is not passed and `parFunc` and `initialArgs` are missing, `forkrun` will silently set `parFunc` to `printf '%s\n'`, which will basically just copy stdin to stdout.
    -u          : unescape redirects/pipes/`&&`/`||`. Un-escapes quoted `<` , `<<` , `<<<` , `>` , `>>` , `|` , `&&` , and `||` characters to allow for piping, redirection, and logical comparrison to occur *inside the coproc*. 
    --          : end of forkrun options indicator. indicate that all remaining arguments are for the function being parallelized and are not forkrun inputs. This allows using a `parFunc` that begins with a `-`. NOTE: there is no `+<FLAG>` equivilant for `--`.
    -v          : increase verbosity level. This can be passed up to 4 times for progressively more verbose output. +v reduces verbosity level by 1.
    (-h|-?)     : display help text. use `--help=f[lags]` or `--help=a[ll]` for more details about flags that `forkrun` supports. NOTE: you must escape the `?` otherwise the shell can interpret it before passing it to forkrun.
```

Note: flags must be given seperately (`-k -v`, not `-kv`) and must be given before the name of the function being parallelized (any flags given after the function name will be assumed to be initial arguments for the function, not forkrun options). There are also "long" versions of the flags (e.g., `--insert` is the same as `-i`). Run `forkrun --help=all` for a full list of long options/flags.
    

