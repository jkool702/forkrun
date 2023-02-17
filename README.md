# forkrun

`forkrun` is a pure-bash function for parallelizing loops in much the same way that `xargs -P` or `parallel` does, only faster. In my testing, `forkrun` was anywhere from 10-80% faster than `xargs -P $(nproc)` and 100-150% faster than `parallel -m -j $(nproc)`. To be clear, these are the "fast" invocations of xargs and parallel. If you were to compare the "1 line at a time" version of all 3 (`forkrun -l1`, `xargs -P $(nproc) -L 1`, `parallel -j $(nprooc)`), `forkrun` is 7-10x as fast as `xargs` and 20-30x as fast as `parallel`.

`forkrun` in invoked in much the same way as `xargs`:

    echo "inArgs" | forkrun [flags] -- parFunc initialArgs

`forkrun` strives to automatically choose reasonable and near-optimal values for flags, so in most usage scenarios no flags will need to be set to attain maximum performance and speed.


# # # # # How it Works # # # # #

`forkrun` parallelizes loops by running multiple inputs through a script/function in parallel using bash coprocs. `forkrun` is fundementally different than most existing loop parallelization codes in the sense that individual function evaluations are not forked. Rather, initially a number of persistent bash coprocs are forked, and then inputs (passed on stdin) are distributed to these coprocs without any additional forking (or reopening pipes/fd's, or...). This,  combined with the exclusive* use of bash builtins (all of main loop, most of the rest of the code) (these avoid subshell generation, and their associated increase in eecution time), is what makes `forkrun` so fast. 

*(except for the occasional call to an external but highly optimized binary (e.g. sort))


# # # # # Supported Options / Flags # # # # #

`forkrun` supports most of the same flags as `xargs` (with the exception of options intended for interactive use), plus a few additional options that are present in `parallel` but not `xargs`. A quick summary will be provided here - for more info refer to the comment block at the top of the forkrun function, or source forkrun and then run `forkrun --help`. The following flags are supported:

    
    (-j|-p) <#> : set number of worker coprocs
    -l <#>      : set number of lines to pass to the function on each function call. if -l=1 then lines from stdin are piped to the function, otherwise `split` groups lines and saves them to a tempo directory on a [ram]disk
    -i          : replace {} with the inputs passed on stdin (instead of placing them at the end)
    -k          : keep input ordering in output. The 1st output will correspoind to the 1st input, 2nd output to 2nd input, etc.
    -n          : pre-pend each (NULL-seperated) output group with an index describing its input order. This is used by the -k flag codepath to sort the output.
    -t          : set the root directory where the temp files containing lines from stdin will be kept (when -l != 1)
    -d          : specify behavior for deleting these temp files containing stdin when we are done with them / when forkrun exits
    (-0|-z)     : stdin is NULL-seperated, not newline seperated. Implies -s. Incompatable with -l=1.
    -s          : pass stdin to the function being parallelized via stdin ( $parFunc < fileWithLinesFromStdin ) instead of via function inputs  ( $parFunc $(< fileWithLinesFromStdin) )
    --          : indicate that all remaining arguments are for the function being parallelized and are not forkrun inputs
    -v          : increase verbosity. Currently, thie only thing this does is print a summary of forkrun options to stderr after all the inputs have been parsed.
    (-h|-?)     : display detailed help text
    
    

# # # # # Dependencies # # # # #

Where possible, `forkrun` uses bash builtins, making the dependency list quite small. To get full functionality, the following are required. Note: items prefaced with (\*)  require the "full" [GNU coreutils] version. Items prefaced with (x) will work with the full version or the busybox version

    (*) bash 4.0+
    (*) split
    (*) grep
    (*) sort (only for '-k' flag)
    (*) cut  (only for '-k' flag)
    (x) wc
    (x) which
    (x) cat
    (x) mktemp
    (*) inotifywait || (x) sleep
    
