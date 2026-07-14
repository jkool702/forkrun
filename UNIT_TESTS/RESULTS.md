=== forkrun v3.4.1 C Plugin Test Suite ===
UNIT_TESTS_DIR : /mnt/ramdisk/forkrun/UNIT_TESTS
FRUN_SCRIPT    : /mnt/ramdisk/forkrun/UNIT_TESTS/frun.bash
Sourcing frun.bash...
Copying header...
✓ Header copied successfully.
✓ Plugins compiled successfully.
Generating test inputs...
Generating variable-length input (~3M lines)...
Only 952229 lines found. Duplicating...
✓ Generated 3000000 lines.

=== Running C Plugin Tests ===

────────────────────────────────────
TEST: Basic Plugin (1M)
Cmd : frun -C ./test_basic.so:test_basic < input_1M.txt
✓ Passed
────────────────────────────────────
TEST: Context Header (1M)
Cmd : frun -C ./test_ctx_header.so:test_ctx_header < input_1M.txt
✓ Passed
────────────────────────────────────
TEST: Context Naked (1M)
Cmd : frun -C ./test_ctx_naked.so:test_ctx_naked < input_1M.txt
✓ Passed
────────────────────────────────────
TEST: High Batch Size (5M)
Cmd : frun -l 1:65535 -C ./test_ctx_header.so:test_ctx_header < input_5M.txt
✓ Passed
────────────────────────────────────
TEST: Variable Length Lines
Cmd : frun -C ./test_ctx_naked.so:test_ctx_naked < input_var_3M.txt
✓ Passed
────────────────────────────────────
TEST: Ordered Output (-k)
Cmd : frun -k -C ./test_basic.so:test_basic < input_1M.txt
✓ Passed

=== All C Plugin Tests Completed Successfully ===

=== forkrun v3.4.1 C Plugin Rigorous Test Suite ===
Compiling Native Plugins...
Generating Deterministic Test Inputs...
------------------------------------------------------
TEST 1: Ordered Data Integrity (-k + Basic Echo)
✓ Passed: Output perfectly matches input (Zero Data Loss)
------------------------------------------------------
TEST 2: Context Math & Byte Accountability
✓ Passed: Context batch_byte_length accurately tracks all 18638895 bytes
------------------------------------------------------
TEST 3: Fault Injection & Retry Semantics (-E)
✓ Passed: Poisoned batch successfully recovered and ordered exactly-once
------------------------------------------------------
=== All C Plugin Rigorous Tests Completed Successfully ===

[1;36m[1m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
[1;36m[1m  FORKRUN COMPREHENSIVE SUPPLEMENTAL TEST SUITE[0m
[1;36m[1m  System: 28 CPUs, 4 NUMA node(s)[0m
[1;36m[1m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m

[1;34m[1m▶ Section A: REGRESSION: Bash Function Transmission[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Regression: simple function reaches workers
  [0;32m✓[0m Regression: function with local vars
  [0;32m✓[0m Regression: function shadows external command (cat)
  [0;32m✓[0m Regression: function called once per line with -l 1
  [0;32m✓[0m Regression: function called with multi-line batch (-l 3, -k)

[1;34m[1m▶ Section B: Bash Functions: Full Coverage[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Function with if/else logic
  [0;32m✓[0m Function with case statement
  [0;32m✓[0m Function producing multiple output lines per input
  [0;32m✓[0m Function using printf
  [0;32m✓[0m Function accessing all args via $@
  [0;32m✓[0m Function with local array operations
  [0;32m✓[0m Function + ordered output (-k)
  [0;32m✓[0m Function + realtime mode (-u)
  [0;32m✓[0m Function + stdin passthrough (-s)
  [0;32m✓[0m Function + insert substitution (-i)
  [0;32m✓[0m Function + record limit (-n 3)
  [0;32m✓[0m Function with explicit $1 reference
  [0;32m✓[0m Function with _underscored_name_123

[1;34m[1m▶ Section C: FORKRUN_EXTRA_FUNCS: Dependent Function Chains[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m FORKRUN_EXTRA_FUNCS: one-level dependency
  [0;32m✓[0m FORKRUN_EXTRA_FUNCS: two-level chain
  [0;32m✓[0m FORKRUN_EXTRA_FUNCS: multiple helpers (space-separated list)
  [0;32m✓[0m FORKRUN_EXTRA_FUNCS: ordered output (-k)
  [0;32m✓[0m FORKRUN_EXTRA_FUNCS: stdin passthrough (-s)
  [0;32m✓[0m FORKRUN_EXTRA_FUNCS: works with --nodes=2
  [0;32m✓[0m FORKRUN_EXTRA_FUNCS: missing helper causes worker error (not silent)

[1;34m[1m▶ Section C2: FORKRUN_EXTRA_VARS: Passing Variables into the Cleanroom[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m FORKRUN_EXTRA_VARS: scalar variable reaches workers
  [0;32m✓[0m FORKRUN_EXTRA_VARS: multiple variables (space-separated)
  [0;32m✓[0m FORKRUN_EXTRA_VARS: variable value containing spaces
  [0;32m✓[0m FORKRUN_EXTRA_VARS: numeric variable used in arithmetic
  [0;32m✓[0m FORKRUN_EXTRA_VARS + FORKRUN_EXTRA_FUNCS: combined
  [0;32m✓[0m FORKRUN_EXTRA_VARS: ordered output (-k)
  [0;32m✓[0m FORKRUN_EXTRA_VARS: available in stdin-mode (-s) function
  [0;32m✓[0m FORKRUN_EXTRA_VARS: unset variable injects as empty string
  [0;32m✓[0m FORKRUN_EXTRA_VARS: array variable injection
  [0;32m✓[0m FORKRUN_EXTRA_VARS: associative array injection
  [0;32m✓[0m FORKRUN_EXTRA_VARS: variable value with special characters
  [0;32m✓[0m FORKRUN_EXTRA_VARS: large variable value (1000 chars)

[1;34m[1m▶ Section D: Data Integrity: No Loss, No Duplication[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m 100-line integrity: default mode (printf passthrough)
  [0;32m✓[0m 100-line integrity: ordered mode (-k)
  [0;32m✓[0m 100-line integrity: stdin mode (-s cat)
  [0;32m✓[0m 1000-line integrity: default mode with -j 8
  [0;32m✓[0m 1000-line integrity: ordered (-k -j 8)
  [0;32m✓[0m Byte mode integrity: -b 10, 100 bytes total
  [0;32m✓[0m Byte mode integrity: non-multiple chunk (-b 30, 100 bytes)
  [0;32m✓[0m Null-delimited integrity (-z, -s)
  [0;32m✓[0m No-duplicate guarantee: workers == line count
  [0;32m✓[0m Custom delimiter integrity (-d :)
  [0;32m✓[0m High-fanout output: 10 inputs * 100 output lines each = 1000 lines

[1;34m[1m▶ Section E: Special Characters in Input[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Glob chars in input survive cmdline mode (* ? [])
  [0;32m✓[0m Dollar sign in input not expanded
  [0;32m✓[0m Backslash in input not consumed
  [0;32m✓[0m Single quotes in input survive quoting
  [0;32m✓[0m Double quotes in input survive quoting
  [0;32m✓[0m Semicolons in input treated as literals
  [0;32m✓[0m Pipe char in input treated as literal
  [0;32m✓[0m Special chars passthrough intact in -s mode
  [0;32m✓[0m Unicode (CJK) characters in input
  [0;32m✓[0m Lines with spaces: each treated as single argument
  [0;32m✓[0m Tabs in input lines survive quoting

[1;34m[1m▶ Section F: Batch Correctness: Exact Arg Counts per Call[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m -l 1: every call gets exactly 1 arg
  [0;32m✓[0m -l 2: every call gets exactly 2 args (10 lines / 2)
  [0;32m✓[0m -l 3: 9 lines produces correct batch count (3 batches)
  [0;32m✓[0m -L 4 (exact): verify all batch sizes are 4 (with 8 lines)
  [0;32m✓[0m -l 3 -k: first batch contains correct args in order
  [0;32m✓[0m -l 3 -s -k: batch content passed as stdin correctly

[1;34m[1m▶ Section G: Sequential Invocations: Ring Reuse[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Two sequential frun calls produce correct independent output
  [0;32m✓[0m Three sequential frun calls
  [0;32m✓[0m Sequential: first call ordered, second call unordered
  [0;32m✓[0m Sequential: different -l values between calls
  [0;32m✓[0m Sequential: bash functions in each call independently defined
  [0;32m✓[0m No output leakage between sequential calls

[1;34m[1m▶ Section H: Combined Feature Interactions[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Bash function + NUMA (--nodes=2)
  [0;32m✓[0m Bash function + stdin byte mode (-b -s)
  [0;32m✓[0m Bash function + -i substitution
  [0;32m✓[0m Bash function + -n limit + -k order
  [0;32m✓[0m FORKRUN_EXTRA_FUNCS + NUMA (--nodes=2)
  [0;32m✓[0m Bash function + null delimiter (-z -s)
  [0;32m✓[0m Bash function + custom delimiter (-d :)
  [0;32m✓[0m Bash function + 1000-line ordered integrity (-k)
  [0;32m✓[0m Bash function + unsafe mode (-U)
  [0;32m✓[0m Bash function: stdout ordering unaffected by stderr writes

[1;34m[1m▶ Section I: Boundary Conditions[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Empty input: no output, exit 0
  [0;32m✓[0m Single line input
  [0;32m✓[0m Batch size > input size (-l 100 for 1 line)
  [0;32m✓[0m Input exactly equals batch size (-l 5, 5 lines)
  [0;32m✓[0m Input = batch-size + 1 (-l 5, 6 lines)
  [0;32m✓[0m Input = batch-size - 1 (-l 5, 4 lines)
  [0;32m✓[0m More workers than input lines (-j 50 for 5 lines)
  [0;32m✓[0m Single worker (-j 1) with ordered output
  [0;32m✓[0m Single batch covers entire input (-l 1000000 for 10 lines)
  [0;32m✓[0m Limit equals input size (-n 10 for 10-line input)
  [0;32m✓[0m Limit of 1 (-n 1)
  [0;32m✓[0m Limit of 0 (-n 0): exits cleanly (no hang)
  [0;32m✓[0m Very long line (5000 chars): survives quoting and SIMD scanner
  [0;32m✓[0m Trickle input: early flush delivers all lines (-k)

[1;34m[1m▶ Section J: Worker and ID Semantics[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m -I flag: batch ID format is {NODE.WORKER.BATCH}
  [0;32m✓[0m -I flag: all IDs in a 10-line run are unique
  [0;32m✓[0m Worker failure (false): pipeline survives without deadlock
  [0;32m✓[0m Worker stderr output doesn't corrupt stdout

[1;34m[1m▶ Section K: Framework Self-Tests[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
Verifying run_test_sorted catches missing lines...
  [0;31m✗[0m _selftest_sorted_catches_missing[0;31m — line count: got 2, expected 3[0m
  [0;32m✓[0m run_test_sorted correctly caught a missing line
Verifying run_test_sorted catches duplicate lines...
  [0;31m✗[0m _selftest_sorted_catches_duplicate[0;31m — line count: got 3, expected 2[0m
  [0;32m✓[0m run_test_sorted correctly caught a duplicate line

[1;34m[1m▶ Section L: Fault Resilience: Escrow, Poison, and Self-Healing[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m L1a: One-time crash self-heals (ordered, -k)
  [0;32m✓[0m L1b: One-time crash self-heals (unordered)
  [0;32m✓[0m L1c: One-time crash on first line self-heals (-k)
  [0;32m✓[0m L1d: One-time crash on last line self-heals (-k)
  [0;32m✓[0m L2a: Persistent crash: surviving lines output correctly (-k)
  [0;32m✓[0m L2b: Persistent crash: surviving lines output correctly (unordered)
  [0;32m✓[0m L2c: Persistent crash on 2 values: both lost, rest survive
  [0;32m✓[0m L2d: Persistent crash in batch mode (-l 5): poisoned batch fully discarded
  [0;32m✓[0m L2e: Persistent crash with exit 139: surviving lines correct
  [0;32m✓[0m L3a: Mid-batch crash: partial output discarded (-k)
  [0;32m✓[0m L3b: Mid-batch crash: no partial/corrupt output leaks
  [0;32m✓[0m L3c: Mid-batch crash: partial output NOT in stdout (grep check)
  [0;32m✓[0m L4a: One-time crash produces no duplicate output
  [0;32m✓[0m L4b: Self-heal: output has exact expected line count (10)
  [0;32m✓[0m L4c: One-time crash self-heals with NUMA (--nodes=2, -k)
  [0;32m✓[0m L5a: Ordered output after failure preserves input order (-k)
  [0;32m✓[0m L5b: Ordered output with 2 persistent failures (-k)
  [0;32m✓[0m L5c: Ordered self-heal: all lines in correct order (-k)
  [0;32m✓[0m L6a: Workers exiting 0 are not respawned (no duplicate lines)
  [0;32m✓[0m L6b: Explicit exit 0 in function: no duplicates
  [0;32m✓[0m L7a: Multiple failing workers: surviving lines correct
  [0;32m✓[0m L7b: Serialized (-j 1) with persistent failure: correct surviving output
  [0;32m✓[0m L7c: High failure rate (every 3rd line): survivors correct
  [0;32m✓[0m L8a: Large batch (-l 10): poisoned batch discarded, rest intact
  [0;32m✓[0m L8b: Large batch (-l 10) one-time crash: all lines survive (-k)
  [0;32m✓[0m L9a: Stdin mode (-s) with persistent crash: surviving lines correct
  [0;32m✓[0m L9b: Stdin mode (-s -k) with persistent crash: order preserved
  [0;32m✓[0m L9c: Stdin mode (-s -k) one-time crash: self-heals
  [0;32m✓[0m L10a: Persistent crash + unsafe mode (-U): survivors correct
  [0;32m✓[0m L10b: One-time crash + FORKRUN_EXTRA_VARS: var survives respawn (-k)
  [0;32m✓[0m L10c: One-time crash + FORKRUN_EXTRA_FUNCS chain: helper survives (-k)
  [0;32m✓[0m L10d: Persistent crash + NUMA (--nodes=2): survivors correct
  [0;32m✓[0m L10e: Persistent crash + limit (-n 5 -k): 4 surviving lines from 5 inputs
  [0;32m✓[0m L10f: Persistent crash + --buffered: survivors correct
  [0;32m✓[0m L10g: Persistent crash + -i insert mode: survivors correct
  [0;32m✓[0m L10h: Byte mode (-b 25): all chunks processed, correct total bytes
  [0;32m✓[0m L11a: 5x stress: one-time crash always self-heals
  [0;32m✓[0m L12a: All lines crash: pipeline terminates, empty output
  [0;32m✓[0m L12b: All lines crash (-k): pipeline terminates (no hang)
  [0;32m✓[0m L13: Single crashing line: empty output, clean exit
  [0;32m✓[0m L14: Worker outputs 2 lines then crashes: partial output discarded
  [0;32m✓[0m L15: 100 lines, 1 persistent crash: 99 surviving lines
  [0;32m✓[0m L16a: Worker SIGKILL: full teardown, pipeline terminates
  [0;32m✓[0m L16b: Worker SIGKILL after partial output: no corruption
  [0;32m✓[0m L16c: Worker SIGKILL in -k mode: pipeline terminates
  [0;32m✓[0m L16d: Worker SIGKILL in -s mode: no deadlock
  [0;32m✓[0m L16e: Worker SIGKILL with -j 4: surviving workers shut down
  [0;32m✓[0m L17a: Scanner EOF (input closes early): pipeline terminates
  [0;32m✓[0m L17b: Scanner failure (input dies mid-stream): pipeline terminates
  [0;32m✓[0m L17c: Scanner failure with -k: pipeline terminates (no hang)
  [0;32m✓[0m L17d: Scanner failure mid-processing: no corrupted output
  [0;32m✓[0m L17e: Scanner failure in -s mode: no deadlock

[1;34m[1m▶ Section M: Checkpoint & Resume[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m M1: Checkpoint file created on worker SIGKILL (-k)
  [0;32m✓[0m M2: Checkpoint contains resume horizon state
  [0;32m✓[0m M3: Checkpoint contains FORKRUN_ORIG_ARGS
  [0;32m✓[0m M4: Resume produces complete output (-k)
  [0;32m✓[0m M5: Resume with buffered mode
  [0;32m✓[0m M6: Resume with realtime mode (-u)
  [0;32m✓[0m M7: Resume with stdin mode (-s)
  [0;32m✓[0m M8: Resume with byte mode (-b)
  [0;32m✓[0m M9: Resume preserves FORKRUN_EXTRA_VARS
  [0;32m✓[0m M10: Resume preserves FORKRUN_EXTRA_FUNCS
  [0;32m✓[0m M11: Missing resume file error
  [0;32m✓[0m M12: Resume with NUMA (--nodes=2)
  [0;32m✓[0m M13: Ordered output correct after resume (-k)
  [0;32m✓[0m M14: No duplicates after resume (exactly-once)
  [0;32m✓[0m M15: Resume with -i insert mode
  [0;32m✓[0m M16: Checkpoint byte count produces clean truncation

[1;34m[1m▶ Section N: Property-Based Invariants (Randomized)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m N1: Default sorted == Ordered, random inputs
  [0;32m✓[0m N2: No data loss, random inputs
  [0;32m✓[0m N3: No duplication, random inputs
  [0;32m✓[0m N4: Stdin sorted == Ordered stdin, random inputs
  [0;32m✓[0m N5: Byte mode byte count integrity, various sizes

[1;34m[1m▶ Section O: Configuration Edge Cases[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m O1: -b 1k (1000 bytes)
  [0;32m✓[0m O2: -b 1Ki (1024 bytes)
  [0;32m✓[0m O3: -b 1M (1,000,000 bytes)
  [0;32m✓[0m O4: -l 1k (1000 lines per batch)
  [0;32m✓[0m O5: -j 1:4 worker range
  [0;32m✓[0m O6: Negative limit value handled
  [0;32m✓[0m O7: Zero batch size defaults correctly
  [0;32m✓[0m O8: -b 1G large chunk size works
  [0;32m✓[0m O9: -b 16E overflow clamps with warning

[1;34m[1m▶ Section P: Exit Code Correctness[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m P1: Successful run exits 0
  [0;32m✓[0m P2: Missing resume file exits non-zero
  [0;32m✓[0m P3: Worker failure without -E exits 0
  [0;32m✓[0m P4: Poisoned batch exits non-zero
  [0;32m✓[0m P5: Poisoned batch produces stderr warning
  [0;32m✓[0m P6: Partial poisoning: 99/100 lines + non-zero exit
  [0;32m✓[0m P7: Setup failure propagates exit 42
  [0;32m✓[0m P8: SIGPIPE exits cleanly

[1;34m[1m▶ Section Q: Concurrent Invocation Stress[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Q1: Two concurrent frun calls independent
  [0;32m✓[0m Q2: Concurrent frun with different modes
  [0;32m✓[0m Q3: Concurrent frun with separate checkpoints
  [0;32m✓[0m Q4: Sequential frun reuse, 10 iterations

[1;34m[1m▶ Section R: v3.4.1 New Features (TUI, SLURM, Halt, Sweeps)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m R1: TUI flag accepted and pipeline completes (headless safe)
  [0;32m✓[0m R2: SLURM SIGUSR1 triggers checkpoint and exit 138
  [0;32m✓[0m R3: Auto halt on absolute fail count (--halt fail=2)
  [0;32m✓[0m R4: Auto halt on percentage (--halt fail=50%)
  [0;32m✓[0m R5: Sweep inline args (:::) with {1}-{2}
  [0;32m✓[0m R6: Sweep inline args (:::) default args
  [0;32m✓[0m R7: Sweep file args (::::) default args
  [0;32m✓[0m R8: Sweep --link zip mode
  [0;32m✓[0m R9: Sweep with bash function
  [0;32m✓[0m R10: SLURM SIGTERM triggers checkpoint and exit 143
  [0;32m✓[0m R11: GNU Halt syntax (--halt now,2) triggers abort
  [0;32m✓[0m R12: Sweep file args from stdin (:::: -)
  [0;32m✓[0m R13: Sweep --link truncates uneven arrays safely

[1;36m[1m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
[1mSUMMARY[0m
[1;36m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
Total:   208
Passed:  208  ([0;32m100.0%[0m)
Failed:    0  ([0;31m0.0%[0m)
Skipped:   0  ([1;33m0.0%[0m)

[0;32m[1mALL TESTS PASSED![0m
[0;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m

[1;34m[1m▶ Core Modes (Default, Ordered, Realtime)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Default mode
  [0;32m✓[0m Ordered mode (-k)
  [0;32m✓[0m Realtime mode (-u)
  [0;32m✓[0m Buffered ordered (--buffered -k)

[1;34m[1m▶ Input Handling (stdin, bytes, delimiters)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Stdin mode (-s)
  [0;32m✓[0m Byte mode (-b 10)
  [0;32m✓[0m Byte mode (-b 50)
  [0;32m✓[0m Custom delimiter (-d :)
  [0;32m✓[0m Null delimiter (-z)
  [0;32m✓[0m Unicode support

[1;34m[1m▶ Batch Size Control (lines, bytes, exact)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Fixed batch size (-l 2)
  [0;32m✓[0m Batch size range (-l 1:5)
  [0;32m✓[0m Exact lines (-L 3)
  [0;32m✓[0m Exact lines with limit (-L 4 -n 8)

[1;34m[1m▶ Worker Scaling (-j)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Fixed workers (-j 2)
  [0;32m✓[0m Worker range (-j 1:4)
  [0;32m✓[0m Oversubscribe (--nodes=@2)

[1;34m[1m▶ Limits and Timeouts[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Record limit (-n 5)
  [0;32m✓[0m Limit with unordered (-n 5)
  [0;32m✓[0m Timeout flag accepted (--timeout 50000)

[1;34m[1m▶ String Substitution (-i, -I)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Insert mode (-i)
  [0;32m✓[0m Insert ID mode (-I)
  [0;32m✓[0m Insert with custom command (-i)

[1;34m[1m▶ Quoting and Unsafe Mode[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Safe quoting with spaces
  [0;32m✓[0m Unsafe mode (-U) with spaces
  [0;32m✓[0m Explicit safe mode (+U)

[1;34m[1m▶ Output Mode Combinations[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Stdin + ordered (-s -k)
  [0;32m✓[0m Byte + realtime (-b 10 -u)
  [0;32m✓[0m Byte + ordered (-b 50 -k)
  [0;32m✓[0m Exact lines + stdin (-L 3 -s)

[1;34m[1m▶ NUMA Topology[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Auto NUMA (--nodes=auto)
  [0;32m✓[0m Explicit nodes (--nodes=0)
  [0;32m✓[0m Multi-node (--nodes=2)
  [0;32m✓[0m Exact lines with NUMA (downgrade warning)

[1;34m[1m▶ Special Flags[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Dry run (-N)
  [0;32m✓[0m Version (-V)
  [0;32m✓[0m Help (--help)
  [0;32m✓[0m Verbose flag (-v)
  [0;32m✓[0m Stats flag (--stats)

[1;34m[1m▶ Edge Cases[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Empty input
  [0;32m✓[0m Single line input
  [0;32m✓[0m Batch larger than input (-l 100)
  [0;32m✓[0m More workers than lines (-j 20)
  [0;32m✓[0m Tab characters

[1;34m[1m▶ Complex Flag Combinations[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Combination: -s -k -n 5
  [0;32m✓[0m Combination: -b 20 -u -j 2
  [0;32m✓[0m Combination: --nodes=2 -j 4 -l 2 -k
  [0;32m✓[0m Combination: -L 2 --timeout 100000 -v
  [0;32m✓[0m Combination: -b 33 --nodes=auto -s

[1;34m[1m▶ Performance & Stress (Quick Checks)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Large input (1000 lines) default
  [0;32m✓[0m Large input with -j 8
  [0;32m✓[0m Large byte input (10k) -b 1024

[1;34m[1m▶ Alias Flags[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Alias: --atomic (buffered)
  [0;32m✓[0m Alias: --keep-order
  [0;32m✓[0m Alias: --unbuffered

[1;34m[1m▶ Deep Architecture (Zero-Copy, Trickle, SIMD)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Direct file ingest (Zero-Copy UMA)
  [0;32m✓[0m Direct file ingest (Zero-Copy NUMA)
  [0;32m✓[0m Direct file ingest (Byte Mode)
  [0;32m✓[0m AVX2/NEON SIMD long-line boundaries
  [0;32m✓[0m Trickle input (Early Flush / Stall Meter)
  [0;32m✓[0m Command failure tolerance (No Deadlock)

[1;34m[1m▶ Bash Execution Environment & State Propagation[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Parallelize simple bash function
  [0;32m✓[0m Parallelize nested bash functions
  [0;32m✓[0m Exported variables propagate
  [0;32m✓[0m Unexported variables do not propagate

[1;34m[1m▶ Engine Physics: Escrow, Skew, and Heap Stress[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m ring_order Min-Heap with Severe Skew (-k)
  [0;32m✓[0m Forced Escrow Steal (Single Worker Overshoot)
  [0;32m✓[0m Massive Oversubscription (128 workers, 10 lines)

[1;34m[1m▶ I/O Edge Cases & Scanner Boundaries[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m File with NO trailing newline
  [0;32m✓[0m Exact Limit matching

[1;34m[1m▶ Routing: Data as Arguments (Default)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Default mode passes data as arguments
  [0;32m✓[0m Default mode passes filenames to cat

[1;34m[1m▶ Routing: Data Spliced to Stdin (-s / -b)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Stdin mode (-s) splices to worker stdin
  [0;32m✓[0m Byte mode (-b) splices to worker stdin

[1;34m[1m▶ Variable Serialization (FORKRUN_EXTRA_VARS)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m FORKRUN_EXTRA_VARS passes simple strings
  [0;32m✓[0m FORKRUN_EXTRA_VARS passes standard arrays
  [0;32m✓[0m FORKRUN_EXTRA_VARS passes associative arrays

[1;34m[1m▶ Custom clean-room setup (FORKRUN_EXTRA_SETUP)[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m FORKRUN_EXTRA_SETUP: set env var used by worker
  [0;32m✓[0m FORKRUN_EXTRA_SETUP: enable extglob affects pattern matching
  [0;32m✓[0m FORKRUN_EXTRA_SETUP: setup executes before function capture
  [0;32m✓[0m FORKRUN_EXTRA_SETUP: failing setup code propagates exact exit code

[1;34m[1m▶ Signal Handling and Early Termination[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Graceful SIGPIPE handling (head -n 5)
  [0;32m✓[0m Worker transient failure mid-batch
  [0;32m✓[0m Worker one-time transient failure mid-batch

[1;34m[1m▶ Misc additional tests[0m
[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
  [0;32m✓[0m Min-heap ordering: 100 batches with random sleep skew
  [0;32m✓[0m SIGPIPE cascade: orderer dies, workers abort cleanly
  [0;32m✓[0m Byte mode: UTF-8 character integrity (10 bytes for 5 Greek chars)
  [0;32m✓[0m Operates correctly under moderate FD limits (ulimit -n 256)
  [0;32m✓[0m Timeout flush: 50ms timeout delivers trickle input

[1;36m[1m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
[1;36m[1m  FORKRUN TEST SUITE[0m
[1;36m[1m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
[1mTEST SUMMARY[0m
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total:   89
Passed:  89 ([0;32m100.0%[0m)
Failed:   0 ([0;31m0.0%[0m)
Skipped:   0 ([1;33m0.0%[0m)

[0;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
[0;32m[1mALL TESTS PASSED![0m
[0;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
