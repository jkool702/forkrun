./test_frun.sh

▶ Core Modes (Default, Ordered, Realtime)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Default mode
  ✓ Ordered mode (-k)
  ✓ Realtime mode (-u)
  ✓ Buffered ordered (--buffered -k)

▶ Input Handling (stdin, bytes, delimiters)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Stdin mode (-s)
  ✓ Byte mode (-b 10)
  ✓ Byte mode (-b 50)
  ✓ Custom delimiter (-d :)
  ✓ Null delimiter (-z)
  ✓ Unicode support

▶ Batch Size Control (lines, bytes, exact)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Fixed batch size (-l 2)
  ✓ Batch size range (-l 1:5)
  ✓ Exact lines (-L 3)
  ✓ Exact lines with limit (-L 4 -n 8)

▶ Worker Scaling (-j)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Fixed workers (-j 2)
  ✓ Worker range (-j 1:4)
  ✓ Oversubscribe (--nodes=@2)

▶ Limits and Timeouts
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Record limit (-n 5)
  ✓ Limit with unordered (-n 5)
  ✓ Timeout flag accepted (--timeout 50000)

▶ String Substitution (-i, -I)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Insert mode (-i)
  ✓ Insert ID mode (-I)
  ✓ Insert with custom command (-i)

▶ Quoting and Unsafe Mode
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Safe quoting with spaces
  ✓ Unsafe mode (-U) with spaces
  ✓ Explicit safe mode (+U)

▶ Output Mode Combinations
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Stdin + ordered (-s -k)
  ✓ Byte + realtime (-b 10 -u)
  ✓ Byte + ordered (-b 50 -k)
  ✓ Exact lines + stdin (-L 3 -s)

▶ NUMA Topology
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Auto NUMA (--nodes=auto)
  ✓ Explicit nodes (--nodes=0)
  ✓ Multi-node (--nodes=2)
  ✓ Exact lines with NUMA (downgrade warning)

▶ Special Flags
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Dry run (-N)
  ✓ Version (-V)
  ✓ Help (--help)
  ✓ Verbose flag (-v)
  ✓ Stats flag (--stats)

▶ Edge Cases
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Empty input
  ✓ Single line input
  ✓ Batch larger than input (-l 100)
  ✓ More workers than lines (-j 20)
  ✓ Tab characters

▶ Complex Flag Combinations
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Combination: -s -k -n 5
  ✓ Combination: -b 20 -u -j 2
  ✓ Combination: --nodes=2 -j 4 -l 2 -k
  ✓ Combination: -L 2 --timeout 100000 -v
  ✓ Combination: -b 33 --nodes=auto -s

▶ Performance & Stress (Quick Checks)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Large input (1000 lines) default
  ✓ Large input with -j 8
  ✓ Large byte input (10k) -b 1024

▶ Alias Flags
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Alias: --atomic (buffered)
  ✓ Alias: --keep-order
  ✓ Alias: --unbuffered

▶ Deep Architecture (Zero-Copy, Trickle, SIMD)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Direct file ingest (Zero-Copy UMA)
  ✓ Direct file ingest (Zero-Copy NUMA)
  ✓ Direct file ingest (Byte Mode)
  ✓ AVX2/NEON SIMD long-line boundaries
  ✓ Trickle input (Early Flush / Stall Meter)
  ✓ Command failure tolerance (No Deadlock)

▶ Bash Execution Environment & State Propagation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Parallelize simple bash function
  ✓ Parallelize nested bash functions
  ✓ Exported variables propagate
  ✓ Unexported variables do not propagate

▶ Engine Physics: Escrow, Skew, and Heap Stress
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ ring_order Min-Heap with Severe Skew (-k)
  ✓ Forced Escrow Steal (Single Worker Overshoot)
  ✓ Massive Oversubscription (128 workers, 10 lines)

▶ I/O Edge Cases & Scanner Boundaries
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ File with NO trailing newline
  ✓ Exact Limit matching

▶ Routing: Data as Arguments (Default)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Default mode passes data as arguments
  ✓ Default mode passes filenames to cat

▶ Routing: Data Spliced to Stdin (-s / -b)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Stdin mode (-s) splices to worker stdin
  ✓ Byte mode (-b) splices to worker stdin

▶ Variable Serialization (FORKRUN_EXTRA_VARS)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ FORKRUN_EXTRA_VARS passes simple strings
  ✓ FORKRUN_EXTRA_VARS passes standard arrays
  ✓ FORKRUN_EXTRA_VARS passes associative arrays

▶ Custom clean-room setup (FORKRUN_EXTRA_SETUP)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ FORKRUN_EXTRA_SETUP: set env var used by worker
  ✓ FORKRUN_EXTRA_SETUP: enable extglob affects pattern matching
  ✓ FORKRUN_EXTRA_SETUP: setup executes before function capture
  ✓ FORKRUN_EXTRA_SETUP: failing setup code propagates exact exit code

▶ Signal Handling and Early Termination
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Graceful SIGPIPE handling (head -n 5)
  ✓ Worker transient failure mid-batch
  ✓ Worker one-time transient failure mid-batch

▶ Misc additional tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Min-heap ordering: 100 batches with random sleep skew
  ✓ SIGPIPE cascade: orderer dies, workers abort cleanly
  ✓ Byte mode: UTF-8 character integrity (10 bytes for 5 Greek chars)
  ✓ Operates correctly under moderate FD limits (ulimit -n 256)
  ✓ Timeout flush: 50ms timeout delivers trickle input

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FORKRUN TEST SUITE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TEST SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total:   89
Passed:  89 (100.0%)
Failed:   0 (0.0%)
Skipped:   0 (0.0%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ALL TESTS PASSED!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

./test_frun_comprehensive.sh

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FORKRUN COMPREHENSIVE SUPPLEMENTAL TEST SUITE
  System: 28 CPUs, 1 NUMA node(s)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

▶ Section A: REGRESSION: Bash Function Transmission
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Regression: simple function reaches workers
  ✓ Regression: function with local vars
  ✓ Regression: function shadows external command (cat)
  ✓ Regression: function called once per line with -l 1
  ✓ Regression: function called with multi-line batch (-l 3, -k)

▶ Section B: Bash Functions: Full Coverage
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Function with if/else logic
  ✓ Function with case statement
  ✓ Function producing multiple output lines per input
  ✓ Function using printf
  ✓ Function accessing all args via $@
  ✓ Function with local array operations
  ✓ Function + ordered output (-k)
  ✓ Function + realtime mode (-u)
  ✓ Function + stdin passthrough (-s)
  ✓ Function + insert substitution (-i)
  ✓ Function + record limit (-n 3)
  ✓ Function with explicit $1 reference
  ✓ Function with _underscored_name_123

▶ Section C: FORKRUN_EXTRA_FUNCS: Dependent Function Chains
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ FORKRUN_EXTRA_FUNCS: one-level dependency
  ✓ FORKRUN_EXTRA_FUNCS: two-level chain
  ✓ FORKRUN_EXTRA_FUNCS: multiple helpers (space-separated list)
  ✓ FORKRUN_EXTRA_FUNCS: ordered output (-k)
  ✓ FORKRUN_EXTRA_FUNCS: stdin passthrough (-s)
  ✓ FORKRUN_EXTRA_FUNCS: works with --nodes=2
  ✓ FORKRUN_EXTRA_FUNCS: missing helper causes worker error (not silent)

▶ Section C2: FORKRUN_EXTRA_VARS: Passing Variables into the Cleanroom
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ FORKRUN_EXTRA_VARS: scalar variable reaches workers
  ✓ FORKRUN_EXTRA_VARS: multiple variables (space-separated)
  ✓ FORKRUN_EXTRA_VARS: variable value containing spaces
  ✓ FORKRUN_EXTRA_VARS: numeric variable used in arithmetic
  ✓ FORKRUN_EXTRA_VARS + FORKRUN_EXTRA_FUNCS: combined
  ✓ FORKRUN_EXTRA_VARS: ordered output (-k)
  ✓ FORKRUN_EXTRA_VARS: available in stdin-mode (-s) function
  ✓ FORKRUN_EXTRA_VARS: unset variable injects as empty string
  ✓ FORKRUN_EXTRA_VARS: array variable injection
  ✓ FORKRUN_EXTRA_VARS: associative array injection
  ✓ FORKRUN_EXTRA_VARS: variable value with special characters
  ✓ FORKRUN_EXTRA_VARS: large variable value (1000 chars)

▶ Section D: Data Integrity: No Loss, No Duplication
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ 100-line integrity: default mode (printf passthrough)
  ✓ 100-line integrity: ordered mode (-k)
  ✓ 100-line integrity: stdin mode (-s cat)
  ✓ 1000-line integrity: default mode with -j 8
  ✓ 1000-line integrity: ordered (-k -j 8)
  ✓ Byte mode integrity: -b 10, 100 bytes total
  ✓ Byte mode integrity: non-multiple chunk (-b 30, 100 bytes)
  ✓ Null-delimited integrity (-z, -s)
  ✓ No-duplicate guarantee: workers == line count
  ✓ Custom delimiter integrity (-d :)
  ✓ High-fanout output: 10 inputs * 100 output lines each = 1000 lines

▶ Section E: Special Characters in Input
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Glob chars in input survive cmdline mode (* ? [])
  ✓ Dollar sign in input not expanded
  ✓ Backslash in input not consumed
  ✓ Single quotes in input survive quoting
  ✓ Double quotes in input survive quoting
  ✓ Semicolons in input treated as literals
  ✓ Pipe char in input treated as literal
  ✓ Special chars passthrough intact in -s mode
  ✓ Unicode (CJK) characters in input
  ✓ Lines with spaces: each treated as single argument
  ✓ Tabs in input lines survive quoting

▶ Section F: Batch Correctness: Exact Arg Counts per Call
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ -l 1: every call gets exactly 1 arg
  ✓ -l 2: every call gets exactly 2 args (10 lines / 2)
  ✓ -l 3: 9 lines produces correct batch count (3 batches)
  ✓ -L 4 (exact): verify all batch sizes are 4 (with 8 lines)
  ✓ -l 3 -k: first batch contains correct args in order
  ✓ -l 3 -s -k: batch content passed as stdin correctly

▶ Section G: Sequential Invocations: Ring Reuse
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Two sequential frun calls produce correct independent output
  ✓ Three sequential frun calls
  ✓ Sequential: first call ordered, second call unordered
  ✓ Sequential: different -l values between calls
  ✓ Sequential: bash functions in each call independently defined
  ✓ No output leakage between sequential calls

▶ Section H: Combined Feature Interactions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Bash function + NUMA (--nodes=2)
  ✓ Bash function + stdin byte mode (-b -s)
  ✓ Bash function + -i substitution
  ✓ Bash function + -n limit + -k order
  ✓ FORKRUN_EXTRA_FUNCS + NUMA (--nodes=2)
./test_frun_comprehensive.sh: line 918: warning: command substitution: ignored null byte in input
./test_frun_comprehensive.sh: line 99: warning: command substitution: ignored null byte in input
  ✓ Bash function + null delimiter (-z -s)
  ✓ Bash function + custom delimiter (-d :)
  ✓ Bash function + 1000-line ordered integrity (-k)
  ✓ Bash function + unsafe mode (-U)
  ✓ Bash function: stdout ordering unaffected by stderr writes

▶ Section I: Boundary Conditions
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ Empty input: no output, exit 0
  ✓ Single line input
  ✓ Batch size > input size (-l 100 for 1 line)
  ✓ Input exactly equals batch size (-l 5, 5 lines)
  ✓ Input = batch-size + 1 (-l 5, 6 lines)
  ✓ Input = batch-size - 1 (-l 5, 4 lines)
  ✓ More workers than input lines (-j 50 for 5 lines)
  ✓ Single worker (-j 1) with ordered output
  ✓ Single batch covers entire input (-l 1000000 for 10 lines)
  ✓ Limit equals input size (-n 10 for 10-line input)
  ✓ Limit of 1 (-n 1)
  ✓ Limit of 0 (-n 0): exits cleanly (no hang)
  ✓ Very long line (5000 chars): survives quoting and SIMD scanner
  ✓ Trickle input: early flush delivers all lines (-k)

▶ Section J: Worker and ID Semantics
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ -I flag: batch ID format is {NODE.WORKER.BATCH}
  ✓ -I flag: all IDs in a 10-line run are unique
  ✓ RING_BATCH_IDX is set and numeric in worker
  ✓ RING_BATCH_SLOTS is set and positive
  ✓ Worker failure (false): pipeline survives without deadlock
  ✓ Worker stderr output doesn't corrupt stdout

▶ Section K: Framework Self-Tests
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Verifying run_test_sorted catches missing lines...
  ✗ _selftest_sorted_catches_missing — line count: got 2, expected 3
  ✓ run_test_sorted correctly caught a missing line
Verifying run_test_sorted catches duplicate lines...
  ✗ _selftest_sorted_catches_duplicate — line count: got 3, expected 2
  ✓ run_test_sorted correctly caught a duplicate line

▶ Section L: Fault Resilience: Escrow, Poison, and Self-Healing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ L1a: One-time crash self-heals (ordered, -k)
  ✓ L1b: One-time crash self-heals (unordered)
  ✓ L1c: One-time crash on first line self-heals (-k)
  ✓ L1d: One-time crash on last line self-heals (-k)
  ✓ L2a: Persistent crash: surviving lines output correctly (-k)
  ✓ L2b: Persistent crash: surviving lines output correctly (unordered)
  ✓ L2c: Persistent crash on 2 values: both lost, rest survive
  ✓ L2d: Persistent crash in batch mode (-l 5): poisoned batch fully discarded
  ✓ L2e: Persistent crash with exit 139: surviving lines correct
  ✓ L3a: Mid-batch crash: partial output discarded (-k)
  ✓ L3b: Mid-batch crash: no partial/corrupt output leaks
  ✓ L3c: Mid-batch crash: partial output NOT in stdout (grep check)
  ✓ L4a: One-time crash produces no duplicate output
  ✓ L4b: Self-heal: output has exact expected line count (10)
  ✓ L4c: One-time crash self-heals with NUMA (--nodes=2, -k)
  ✓ L5a: Ordered output after failure preserves input order (-k)
  ✓ L5b: Ordered output with 2 persistent failures (-k)
  ✓ L5c: Ordered self-heal: all lines in correct order (-k)
  ✓ L6a: Workers exiting 0 are not respawned (no duplicate lines)
  ✓ L6b: Explicit exit 0 in function: no duplicates
  ✓ L7a: Multiple failing workers: surviving lines correct
  ✓ L7b: Serialized (-j 1) with persistent failure: correct surviving output
  ✓ L7c: High failure rate (every 3rd line): survivors correct
  ✓ L8a: Large batch (-l 10): poisoned batch discarded, rest intact
  ✓ L8b: Large batch (-l 10) one-time crash: all lines survive (-k)
  ✓ L9a: Stdin mode (-s) with persistent crash: surviving lines correct
  ✓ L9b: Stdin mode (-s -k) with persistent crash: order preserved
  ✓ L9c: Stdin mode (-s -k) one-time crash: self-heals
  ✓ L10a: Persistent crash + unsafe mode (-U): survivors correct
  ✓ L10b: One-time crash + FORKRUN_EXTRA_VARS: var survives respawn (-k)
  ✓ L10c: One-time crash + FORKRUN_EXTRA_FUNCS chain: helper survives (-k)
  ✓ L10d: Persistent crash + NUMA (--nodes=2): survivors correct
  ✓ L10e: Persistent crash + limit (-n 5 -k): 4 surviving lines from 5 inputs
  ✓ L10f: Persistent crash + --buffered: survivors correct
  ✓ L10g: Persistent crash + -i insert mode: survivors correct
  ✓ L10h: Byte mode (-b 25): all chunks processed, correct total bytes
  ✓ L11a: 5x stress: one-time crash always self-heals
  ✓ L12a: All lines crash: pipeline terminates, empty output
  ✓ L12b: All lines crash (-k): pipeline terminates (no hang)
  ✓ L13: Single crashing line: empty output, clean exit
  ✓ L14: Worker outputs 2 lines then crashes: partial output discarded
  ✓ L15: 100 lines, 1 persistent crash: 99 surviving lines
  ✓ L16a: Worker SIGKILL: full teardown, pipeline terminates
  ✓ L16b: Worker SIGKILL after partial output: no corruption
  ✓ L16c: Worker SIGKILL in -k mode: pipeline terminates
  ✓ L16d: Worker SIGKILL in -s mode: no deadlock
  ✓ L16e: Worker SIGKILL with -j 4: surviving workers shut down
  ✓ L17a: Scanner EOF (input closes early): pipeline terminates
  ✓ L17b: Scanner failure (input dies mid-stream): pipeline terminates
  ✓ L17c: Scanner failure with -k: pipeline terminates (no hang)
  ✓ L17d: Scanner failure mid-processing: no corrupted output
  ✓ L17e: Scanner failure in -s mode: no deadlock

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SUMMARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total:   155
Passed:  155  (100.0%)
Failed:    0  (0.0%)
Skipped:   0  (0.0%)

ALL TESTS PASSED!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
