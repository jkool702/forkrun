# forkrun

`forkrun` is a pure-bash function for parallelizing loops in much the same way that `xargs -P` or `parallel` does, only faster. In my testing, `forkrun` was anywhere from 10-80% faster than `xargs -P $(nproc)` and 100-150% faster than `parallel -m -j $(nproc)`. To be clear, these are the "fast" invocations of xargs and parallel. If you were to compare the "1 line at a time" version of all 3 (`forkrun -l1`, `xargs -P $(nproc) -L 1`, `parallel -j $(nprooc)`), `forkrun` is 7-10x as fast as `xargs` and 20-30x as fast as `parallel`.


# # # # # USAGE # # # # #

`forkrun` in invoked in much the same way as `xargs`: forkrun options, the function that you are parallelizing, and any initial constant arguments are given as function inputs )in that order), and the arguments to parallelize are passed to forkrun on stdin.

    echo "inArgs" | forkrun [flags] -- parFunc [initialArgs]

`forkrun` strives to automatically choose reasonable and near-optimal values for flags, so in most usage scenarios no flags will need to be set to attain maximum performance and speed.

NOTE: you'll need to `source` forkrun before using it

    source /path/to/forkrun.bash
    
Alternately, if you dont have forkrun.bash` saved locally but have internet access, you can run
    
    source <(curl https://raw.githubusercontent.com/jkool702/forkrun/main/forkrun.bash)
    
NO FUNCTION MODE: forkrun supports an additional mode of operation where "parFunc" and "args0" are not given as function inputs, but instead are integrated into each line of "$args". In this mode, each line passed on stin will be run as-is (by saving groups of 512 lines to tmp files and then sourcing them). This allows you to easily run multiple different functions in paralel and still utalize forkrun's very quick and efficient parallelization method. This mode has a few limitations/considerations:

1. The following flags are not supported and, if given, will be ignored: '-i', '-id', '-s' and '-l 1'
2. Lines from stdin will be "space-split" when run. Typically, forkrun splits stdin on newlines (or nulls, if -0z flag is given), allowing (for example)paths that include a space (' ') character to work without needing any quoting. in "no function" mode however, the function and initial args are included in each line on stdin, so they must be space-split to run. Solution is to either quote things containing spaces or easpace the space characters ('\ '). Example:


     `printf '%s\n' 'sha256sum "/some/path/with space character"' 'sha512sum "/some/other/path/with space characters"' | forkrun`


# # # # # HOW IT WORKS # # # # #

`forkrun` parallelizes loops by running multiple inputs through a script/function in parallel using bash coprocs. `forkrun` is fundementally different than most existing loop parallelization codes in the sense that individual function evaluations are not forked. Rather, initially a number of persistent bash coprocs are forked, and then inputs (passed on stdin) are distributed to these coprocs without any additional forking (or reopening pipes/fd's, or...). This,  combined with the exclusive* use of bash builtins (all of main loop, most of the rest of the code) (these avoid subshell generation, and their associated increase in eecution time), is what makes `forkrun` so fast. 

*(except for the occasional call to an external but highly optimized binary (e.g. sort))


# # # # # SUPPORTRED OPTIONS / FLAGS # # # # #

`forkrun` supports most of the same flags as `xargs` (with the exception of options intended for interactive use), plus a few additional options that are present in `parallel` but not `xargs`. A quick summary will be provided here - for more info refer to the comment block at the top of the forkrun function, or source forkrun and then run `forkrun --help`. The following flags are supported:

    
    (-j|-p) <#> : set number of worker coprocs. Default is $(nproc).
    -l <#>      : set number of lines. to pass to the function on each function call. if -l=1 then lines from stdin are piped to the function, otherwise `split` groups lines and saves them to a temp directory on a [ram]disk.
    -i          : replace `{}` with the inputs passed on stdin (instead of placing them at the end)
    -id         : enables -i and also replaces `{id}` with a index (0, 1, ...) describing which coproc the process ran on. Also un-escapes `<` `>` and `|` characters to allow for piping and redirecting output based on which coproc it ran on.
    -k          : keep input ordering in output. The 1st output will correspoind to the 1st input, 2nd output to 2nd input, etc.
    -n          : pre-pend each (NULL-seperated) output group with an index describing its input order. This is used by the -k flag codepath to sort the output.
    -t          : set the root directory where the temp files containing lines from stdin will be kept (when -l != 1)
    -d          : specify behavior for deleting these temp files containing stdin when we are done with them / when forkrun exits
    (-0|-z)     : stdin is NULL-seperated, not newline seperated. Implies -s. Incompatable with -l=1.
    -s          : pass stdin to the function being parallelized via stdin ( $parFunc < fileWithLinesFromStdin ) instead of via function inputs  ( $parFunc $(< fileWithLinesFromStdin) )
    -w          : wait indefinately for the files output by `split` to appear instead oF timing out after 5-10 seconds. Useful if inputs are coming in very slowly on stdin, but could result in forkrun "getting stuck" if stdin is empty (e.g., due to an error).
    --          : indicate that all remaining arguments are for the function being parallelized and are not forkrun inputs
    -v          : increase verbosity. Currently, thie only thing this does is print a summary of forkrun options to stderr after all the inputs have been parsed.
    (-h|-?)     : display detailed help text
    
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
    
