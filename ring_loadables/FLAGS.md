# # # # # FLAGS # # # # #

DATA PASSING FLAGS:

<default>:         pass fully quoted via cmdline ("${A[[@]}")
-U (unsafe):       pass unquoted via cmdline (${A[*]})
-s (stdin):        pass via stdin of code being parallelized (instead of via cmdline)
-b N (bytes mode): instead of splitting on delimiters, split into equal-size sections of N bytes (implies -s)

OUTPUT FLAGS:

<default>:        buffered / "atomic fan in"" mode. output batches are stored in a memfd buffer and printed once the whole batch has finished.
-u (unbuffered):  unbuffered / realtime mode. workers output directly to stdout pipe. can cause massive kernel lock contention in some situations.
-k (ordered):     ordered mode. similar to buffered mode, but output batches are printed in input batch order (instead output batch order). 
