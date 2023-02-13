# forkrun

`forkrun` is a pure-bash function for parallelizing loops in much the same way that `xargs -P` or `parallel` does, only faster. In my testing, `forkrun` was anywhere from 10-80% fastere than `xargs -p` and 100-150% faster than `parallel -m`. `forkrun` in invoked in much the same way as 'xargs':

echo "inArgs" | forkrun [flags] -- parFunc initialArgs

`forkrun` strives to automatically choose reasonable and near-optimal values for flags, so in most usage scenarios no flags will need to be set to attain maximum performance and speed.


# # # # # How it Works # # # # #

`forkrun` runs multiple inputs through a script/function in parallel using bash coprocs. `forkrun` is fundementally different than most existing loop parallelization methods in the sense that individual function evaluations are not forked. Rather, initially a number of persistent bash coprocs are forked, and then inputs (passed on stdin) are distributed to these coprocs without any additional forking.


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
-s          : pass stdin to the function being parallelized via stin instead of via function inputs
--          : indicate that all remaining arguments are for the function being parallelized and are not forkrun inputs
(-h|-?)     : display detailed help text


# # # # # Dependencies # # # # #

Where possible, `forkrun` uses bash builtins, making the dependency list quite small. To get full functionality, the following are required. Note: items prefaced with (*)  require the "full" [GNU coreutils] version. Items without this symbol will work with the busybox version

(*) bash 4.0+
(*) split
(*) sort
(*) cut
which
cat
mktemp
inotifywait || sleep
