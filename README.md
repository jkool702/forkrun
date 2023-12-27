# FORKRUN

`forkrun` is a pure-bash function for parallelizing loops in much the same way that `xargs` or `parallel` does, only faster than either (especially parallel).  In my testing, `forkrun` was, on average (for problems where the efficiency of the parallelization framework acvtually makes a difference) ~70% faster than `xargs -P $(nproc)` and ~7x as fast as `parallel -m -j $(nproc)`. See To be clear, these are the "fast" invocations of xargs and parallel. If you were to compare the "1 line at a time" version of all 3 (`forkrun -l1`, `xargs -P $(nproc) -L 1`, `parallel -j $(nprooc)`), `forkrun` is 7-10x as fast as `xargs` and 20-30x as fast as `parallel`.


## USAGE

`forkrun` in invoked in much the same way as `xargs`: on the command-line, pass forkrun options, then the functionscript/binary that you are parallelizing, then any initial constant arguments (in that order). The arguments to parallelize running are passed to forkrun on stdin. A typical `forkrun` invocation looks something like this:

    printf '%s\n' "${inArgs[@]}" | forkrun [flags] [--] parFunc ["${initialArgs[@]}"]

`forkrun` strives to automatically choose reasonable and near-optimal values for flags, so in most usage scenarios no flags will need to be set to attain maximum performance and speed.

NOTE: you'll need to `source` forkrun before using it

    source /path/to/forkrun.bash
    
Alternately, if you dont have `forkrun.bash` saved locally but have internet access (or want to ensure you are using the latest version), you can run
    
    source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)
    
NO FUNCTION MODE: forkrun supports an additional mode of operation where `parFunc` and `initialArgs` are not given as function inputs, but instead are integrated into each line of "$args". In this mode, each line passed on stin will be run as-is (by saving groups of 512 lines to tmp files and then sourcing them). This allows you to easily run multiple different functions/scripts/binaries in paralel and still utalize forkrun's very quick and efficient parallelization method. To activate this mode, use flag `-N` and do not provide `parFunc` or `initialArgs`.


## HOW IT WORKS

**BASH COPROCS**: `forkrun` parallelizes loops by running multiple inputs through a script/function in parallel using bash coprocs. `forkrun` is fundementally different than most existing loop parallelization codes in the sense that individual function evaluations are not forked. Rather, initially a number of persistent bash coprocs are forked, and then inputs (passed on stdin) are distributed to these coprocs without any additional forking (or reopening pipes/fd's, or...). This,  combined with the (when possible) exclusive use of bash builtins (all of main loop, most of the rest of the code) (these avoid subshell generation, and their associated increase in execution time). This (as well as being *heavily* optimized) is what makes `forkrun` so fast. 

**AUTOMATIC BATCH SIZE ADJUSTMENT**: by default, `forkrun` will automatically dynamically adjust how many lines are passed to the function each time it is called (batch size). The batch size starts at 1, and is dynamically adjusted upwards (but never downwards) up to a maximum of 512 lines per batch (which is typically near-optimal in my personal trial-and-error testing). The logic used here involves:

1. Calculating the average bytes/line by looking number of lines read and number of bytes read (from `/proc/self/fdinfo/$fd`)
2. Estimating the number of remaining lines left to read by getting the difference in number of bytes read/written and dividing by the average bytes/line
3. dividing the estimatedd number of remaining lines by the number of worker coprocs

NOTE: this is a "maximum lines per batch" (implemented via `mapfile -n ${nLines}`)...if stdin is arriving slowly then fewer than this many lines will be used. What this serves to accomplish is to prevent a couple of coproc workers from claiming all the lines of input while the rest sit idle if the total number of lines is less than `512 * (# worker coprocs)`

To overrule this logic and set a static batch size use the '-l' flag. Alternately, use the `-L` flag to keep the auitomatic batch size logic enabled but to change the initial and maximum number of lines per batch.

**IPC**: Forkrun distributes stdin to the worker coprocs by first saving them to a tmpfile (by default on a tmpfs - under `/dev/shm`, customizable with the `-t` flag) using a forked coproc. The worker coprocs then read data from this file using a shared read-only file descriptor and an exclusive read lock. 

## DEPENDENCIES

`forkrun` strives to rely on as few external dependencies as possible. 

**REQUIRED DEPENDENCIES**

Bash 4+ :             This is when coprocs were added. NOTE: `forkrun` will be much faster on bash 5.1+, since it healivy relies of arrays and the `mapfile` command which got a major overhaul in bash 5.1. The vast majority of testing has been done on bash 5.2 so while bash 4-5.0 *should* work it is not well tested.

`rm` and `mkdir`:     For basic filesystem operations that I couldnt figure out how to re-implement in pure bash. Either the GNU or the busybox versions of these will both work.

**OPTIONAL DEPENDENCIES**

Bash 5.1+:           For improved speed due to overhauled handling of arrays.

`mktemp` and `cat`:  The code will provide pure-bash replacements for these if they arent available, but if external binaries for these are present they will be used

`inotifywait`:       If available, this is used to monitor the tmpfile where stdin is saved before being read by the coprocs. This enables the coprocs to efficiently wait for input if stdin is arriving slowly (e.g., `ping 1.1.1.1 | forkrun <...>`)

`fallocate`:         If available, this is used to deallocate already-processed data from the beginning of the tmpfile holding stdin. This enables `forkrun` to be used in long-ruinning processes that consistently output data for days/weeks/months/... Without `fallocate`, this tmpfile will continually grow and will not be removed until forkrun exits 

## WHY USE FORKRUN

## SUPPORTED OPTIONS / FLAGS 

`forkrun` supports many of the same flags as `xargs` (with the exception of options intended for interactive use), plus several additional options that are present in `parallel` but not `xargs`. A quick summary will be provided here - for more info refer to the comment block at the top of the forkrun function, or source forkrun and then run `forkrun --help`. The following flags are supported:

    
    (-j|-p) <#> : num worker coprocs. set number of worker coprocs. Default is $(nproc).
    -l <#>      : num lines per function call (batch size). set number of lines to pass to the function on each function call. if -l=1 (and '-ks' is *not* set). then lines from stdin are piped to the function, otherwise `split` groups lines and saves them to a temp directory on a [ram]disk. Default is '-l=0', which enables automatically adjusing batch size.
    -i          : insert {}. replace `{}` with the inputs passed on stdin (instead of placing them at the end)
    -I         : insert {} and {id}. enables -i and also replaces `{id}` with a index (0, 1, ...) describing which coproc the process ran on. 
    -u          : unescape redirects/pipes/`&&`/`||`. Un-escapes quoted `<` , `<<` , `<<<` , `>` , `>>` , `|` , `&&` , and `||` characters to allow for piping, redirection, and logical comparrison to occur *inside the coproc*. 
    -k          : ordered output. retain input order in output. The 1st output will correspond to the 1st input, 2nd output to 2nd input, etc. Note: ordering is "close but not guaranteed" if flag -l=1 is also given (see '-ks'). Ordering guaranteed for -l>1.
    -n          : add ordering info to output. pre-pend each output group with an index describing its input order, demoted via `$'\n'\n$'\034'$INDEX$'\035'$'\n'`. This repuires and implies the `-k` flag
    -t <path>   : set tmp directoiry. set the directory where the temp files containing lines from stdin will be kept (when -l != 1). These files will be saved inside a new mktemp-generated directory created under the directory specified here,. Default is '/tmp'.
    -d {0,1,2,3}: set tmpdir deletion behavior. specify behavior for deleting the temp files containing stdin when we are done with them / when forkrun exits. Accepts 0, 1, 2, or 3. 0 = never delete, 1 = delete on successful completion, 2 = delete 
    (-0|-z)     : NULL-seperated stdin. stdin is NULL-seperated, not newline seperated. Implies -s. Incompatable with -l=1 (unless '-ks' is also set).
    -s          : pass via function's stdin. pass stdin to the function being parallelized via stdin ( $parFunc < /tmpdir/fileWithLinesFromStdin ) instead of via function inputs  ( $parFunc $(</tmpdir/fileWithLinesFromStdin) )
    -w          : wait for stdin indefinately. wait indefinately for the files output by `split` to appear instead oF timing out after 5-10 seconds. Useful if inputs are coming in very slowly on stdin, but could result in forkrun "getting stuck" if stdin is empty (e.g., due to an error).
    --          : end of forkrun options indicator. indicate that all remaining arguments are for the function being parallelized and are not forkrun inputs
    -v          : increase verbosity. Currently, thie only thing this does is print a summary of forkrun options to stderr after all the inputs have been parsed.
    (-h|-?)     : display detailed help text. Prints the entirety of the oinitial comment block at the start of forkrun.bash to screen.
    
Note: flags are not case sensitive, but must be given seperately (`-k -v`, not `-kv`) and must be given before the name of the function being parallelized (any flags given after the function name will be assumed to be initial arguments for the function, not forkrun options). There are also "long" versions of the flags (e.g., `--insert` is the same as `-i`). Run `forkrun -?` for a full list of long options/flags.
    

# # # # # DEPENDENCIES # # # # #

Where possible, `forkrun` uses bash builtins, making the dependency list quite small. To get full functionality, the following are required. Note: items prefaced with (\*)  require the "full" [GNU coreutils] version. Items prefaced with (x) will work with the full version or the busybox version

    (*) bash 4.0+
    (*) split
    (*) grep (only for '-k' flag)
    (*) sort (only for '-k' flag)
    (*) cut  (only for '-k' flag)
    (x) wc
    (x) which
    (x) cat
    (x) mktemp
    (x) sleep
    
