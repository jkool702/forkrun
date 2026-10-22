# Mandatory Engineering Policy: Single Source of Truth (SSoT)

> **Scope.** This policy governs the decisions a change **introduces,
> modifies, or relies on**. It is not a licence to audit the tree: a
> change that introduces no correctness-critical decision needs no SSoT
> work at all, and a change that touches one decision is in scope for
> *that* decision and not for the rest of the file. Where a change
> touches an existing decision, that decision is in scope -- and so
> are the other places that apply it, because a fix that lands in some
> of them and not others is the failure this policy exists to prevent.
>
> The policy is also not a licence to refactor unrelated code. The
> tests it asks for are about *this* change's decisions.

## 1. Core invariant

**Every specific correctness-critical decision MUST have exactly one authoritative implementation. All code that needs that decision MUST reuse or delegate to that implementation rather than independently reimplementing the decision.**

This is a correctness invariant, not a stylistic preference.

The goal is not merely to eliminate duplicate lines, reduce function counts, or make the code look DRY. The goal is to prevent logically identical decisions from evolving independently, so that fixing a defect in the authoritative implementation fixes the behavior everywhere that decision is used.

This requirement applies to all new and modified code, including AI-generated code, and is especially important when adding features, fixing bugs, supporting another execution mode, or implementing another path through an existing workflow.

**Default assumption: if a correctness-critical decision already exists, extend or reuse its existing authoritative implementation. Do not create a parallel implementation.**

## 2. What counts as a decision?

A decision is any rule that interprets state or inputs to determine a correctness-relevant outcome.

Examples include:

- Choosing whether to fork, wait, retry, continue, or terminate.
- Determining whether a mode, configuration, envelope, flag, or input is valid.
- Classifying a worker, scanner, subprocess, or executor outcome as success, failure, or an expected condition.
- Choosing between an optimized execution path and a fallback.
- Deciding whether an abort, recovery, checkpoint, or cleanup operation is required or has completed.
- Determining whether a record, frame, batch, or transaction has been committed, counted, acknowledged, or completed.
- Deciding how exceptional conditions, timeouts, partial results, and resource exhaustion affect program state.
- Applying common eligibility rules, boundary conditions, or error-classification policies.

A decision can be duplicated without any duplicated function names or identical blocks of code. Two different functions can independently encode the same rule using different variables, control flow, helper calls, or exception handling.

Therefore, **searching for duplicate function bodies alone is insufficient**. Review semantic decisions, not just textual similarity.

### 2.1 Is this decision correctness-critical?

The test is not how important the decision sounds. It is: **does a fix to
this rule have to land in more than one place?**

- If the places are allowed to diverge, the rule is a convention. It may
  be shared for clarity, but nothing breaks when a fix reaches only
  some of them.
- If a fix **must** land in several places -- and a fix landing in
  some of them and not others is a defect waiting to happen -- then the
  rule is correctness-critical, and it has exactly one authoritative
  implementation.

This is the discriminator that keeps the policy from either
over-applying (turning every change into a tree-wide refactor) or
under-applying (sharing a rule that was allowed to drift all along).

## 3. Mandatory workflow before implementing a change

### Step 1: Identify the decision

Before implementing a correctness-sensitive change, determine what decisions the change introduces, modifies, or relies on.

Describe each important decision in terms of:

- The inputs and relevant state.
- The possible outcomes.
- The conditions that select each outcome.
- The invariants that must remain true.
- The existing execution paths that depend on it.

Do not begin by writing a new local implementation and assume that the architecture can be cleaned up later.

### Step 2: Find the existing authoritative implementation

Search the repository before writing new decision logic.

Inspect:

- Existing helpers and their callers.
- Inline conditionals and state transitions.
- Other execution modes, executors, and fallback paths.
- Related exception handlers and cleanup code.
- Existing implementations of the same policy under different names.
- Relevant tests, including tests for previously fixed bugs.

Use both symbol searches and semantic inspection. An existing implementation may not have an obvious name, and equivalent logic may have drifted across several functions.

**Use the block-level scanner, and know why it is the one that matters.**
`tools/ssot_scan.py` compares statement **blocks** -- a function body,
and the body of every if/for/while/try/with/except -- after
canonicalisation. A decision duplicated **inline**, at the point where
the rule is applied, is invisible to a function-level scan by
construction.

That is not a theoretical gap. The abort-aware helper-death rule
(section 11) was applied in **28** places, and a function-level scan
found almost none of them: 26 of the 28 copies were inline. A search
that only compares function bodies reports that this rule has two
implementations, when it has twenty-eight.

The scanner is a **finding tool**, not a gate: it tells you where
duplication is, and section 6 is what makes the finding stick.

Do not assume that an existing helper is irrelevant merely because it does not exactly match the new call site's interface. Determine whether it can be extended, parameterized, or wrapped without duplicating the underlying decision.

If repository access is available, perform these searches directly. If it is not available, disclose that limitation rather than claiming the search was completed.

### Step 3: Reuse the rule, not just its syntax

When the same logical decision already exists:

1. Identify its authoritative implementation.
2. Extend or correct that implementation if necessary.
3. Route the additional caller through it.
4. Remove redundant implementations made obsolete by the change.
5. Preserve caller-specific behavior that occurs *after* the shared decision.

Do not copy the existing logic into a new helper, add another inline conditional, or create a parallel implementation for a newly supported mode merely because doing so appears locally simpler.

Thin adapters and caller-specific wrappers are acceptable when they delegate the decision to the authoritative implementation.

### Step 4: Establish whether apparent differences are real

Similar-looking code does not always implement the same decision. Different execution modes may genuinely have different semantics.

Before consolidating implementations, determine whether their differences are:

- **Incidental differences:** naming, call signatures, duplicated conditions, or historical implementation drift. These generally should be removed.
- **Intentional differences:** distinct policies or contracts required by the execution context. These may remain separate, but the distinction must be explicit and testable.

If the same policy applies in several contexts but requires different follow-up actions, centralize the policy decision and leave those actions in the respective callers.

If two paths genuinely make different decisions, document what makes them different and why. Give the distinct policies clear names where appropriate, and test the behavior that distinguishes them.

Do not preserve duplication simply because it already exists. Equally, do not force two genuinely different policies into one misleading abstraction.

**Divergence is a defect, not a difference to preserve.** When copies
of one rule have drifted -- one consults a check the others do not, one
orders two operations differently, one returns a value the others do
not -- the drift **is** the defect, and centralising it will
legitimately **change behaviour** on the paths that had drifted.

So: resolve it in favour of one implementation, **say which** and why
in the change report, and test it. Do not preserve a divergent copy
"to be safe". A copy that behaves differently from its siblings is the
failure this policy exists to prevent, and preserving it preserves the
failure.

This applies to the order of operations too (section 4.1): if one copy
consults a check *before* an operation and its siblings consult it
*after*, the one that consults after is the broken one, not the odd one
out.

## 4. Separate decisions from actions

**Centralize the decision; do not unnecessarily centralize the entire operation.**

For example, if several executors must determine whether a worker should be forked now, whether the caller must wait, or whether an existing worker can be used, the rule selecting that outcome should live in one authoritative implementation.

Each executor may still perform its own fork operation, update its own state, or handle its own resources.

Likewise, several callers may interpret a scanner's exit status using a shared rule while taking different actions when that rule reports failure.

The following are different responsibilities:

- Determining what an outcome means.
- Determining which response is required.
- Performing the response in a particular execution context.

Centralize each shared correctness-critical decision at the appropriate boundary. Keep context-specific mechanics separate unless those mechanics also embody duplicated policy.

A helper that centralizes the ordinary case but leaves each caller to independently implement exceptional cases does not fully satisfy this policy. The entire shared decision, including its relevant edge cases, must have one authoritative implementation.

### 4.1 The ORDER of operations is part of the decision

A centralised decision includes not only **what** it concludes but the
**order** in which it observes state. A check placed *after* the
operation it is meant to precede can read a state that operation itself
created, and then conclude the opposite every time.

The abort-aware rule is the worked example: it asks whether an abort is
already in flight, and the abort's own call **publishes the reason the
check reads**. A check placed after the abort therefore always sees
"an abort was in flight", and every genuine failure is excused --
silently, because the decision now looks like it works.

So when a decision is centralised, the order is part of what is being
centralised:

- A check that reads state another step **produces** must come first.
- A check that reads state another step **consumes** may come after.
- When the order is load-bearing, it is worth a comment at the
  authoritative implementation, and worth an assertion in the test:
  the test should fail if the order is inverted, not only if the
  outcome is wrong.

### 4.2 A CRITICAL SECTION is a decision: who owns what, across an interruption

A rule enforced in one place, but which can be INTERRUPTED in
another, is not centralised -- it is centralised only on the happy
path.

The canonical case is a forked child. The rule "a child this process
forked is this process's to reap" is implemented in the teardown. But
the teardown can only reap the children it KNOWS about, and that
knowledge is recorded *after* the fork. An exception in the window
between the fork and the record orphans the child: the rule is
centralised, and it still does not hold. Measured: the window was
~100µs against a ~500ms run, and over a gate run (~3000 runs) that
is a ~45% chance of the run leaving a zombie behind.

So ownership of a resource is a decision with two halves:

- **ACQUISITION must be atomic with the acquisition of the resource.**
  A child is adopted at the fork, not at the point where the
  bookkeeping happens to get around to it. Where the acquisition
  cannot be made atomic, there must be ONE authoritative registry
  that records every acquisition and reconciles it at release time --
  not a per-site convention that each site may forget.
- **RELEASE must survive the interruption that would otherwise
  abandon it.** A cleanup sequence that can be interrupted half-way is
  not a cleanup: the resources it had not reached are left behind.
  The interruption is DEFERRED across the section, not swallowed.

**The fork is itself a critical section, and it is easy to forget
that.** CPython's `os.fork()` calls `logging._prepareFork()` in the
PARENT before the syscall and `logging._afterFork()` after it: the
logging module's lock is held across the fork. An asynchronous
exception in that window -- a SIGINT arriving mid-fork -- leaves that
lock held FOREVER, and every later fork in the process then blocks
inside `_prepareFork`. In a threaded caller that is a deadlock: the
forking thread holds the engine session lock while it waits for a
fork that will never return, so the whole suite wedges. Measured: a
process stuck in `logging._prepareFork` while the main thread waited
for the session lock the forking thread held.

So the deferral covers the fork as well as the cleanup, through ONE
primitive, and there is ONE fork helper. A site that calls `os.fork()`
directly has reintroduced the defect this section exists to prevent.

And the release has an ORDER relative to exceptions: a deferred
interruption must not replace an exception that is already
propagating. That exception is the reason for stopping; losing it
loses the diagnosis. (A context manager cannot see an exception
propagating *through* it -- a teardown runs in a `finally` -- so the
wrapper has to say whether the caller was unwinding.)

The same rule governs every operation that can raise between
acquiring a resource and recording the acquisition. The fix is always
the same shape: acquire atomically, or make the window safe.

**One implementation, one contract.** The registry that records
acquisitions and the primitive that defers interruptions are each
singletons. Every fork site adopts its child; every teardown
reconciles the registry; every cleanup sequence runs under the same
deferral. A site that grows its own local guard has reintroduced the
duplication this policy exists to prevent.

## 5. Repeated checks are permitted; repeated rules are not

The invariant concerns the number of authoritative implementations, not the number of times a rule may be evaluated.

For example, separate entry points may all need to validate their inputs. It is acceptable for each entry point to invoke the same validation helper. It is not acceptable for each entry point to independently reimplement the validation policy.

Separate trust boundaries may require separate validation operations. They should still reuse the same underlying rule where their requirements are identical.

Similarly, different callers may independently observe a worker's state, but they must not maintain separate, drifting interpretations of what that state means.

**One authoritative rule can have many consumers and many invocations. It must not have multiple competing implementations.**

## 6. Tests must enforce the architecture as well as the behavior

Tests must demonstrate both that the authoritative decision is correct and that relevant execution paths actually use it.

For a correctness-critical decision:

1. Test the decision's outcomes, boundary conditions, and exceptional cases.
2. Test affected callers or execution modes to establish that they use the authoritative implementation.
3. Add regression coverage for any previously observed divergence between implementations.
4. Verify that consolidation preserves required behavior, including error handling, ordering, cleanup, recovery, and state transitions where applicable.
5. Exercise relevant fallback and disabled-feature paths, not just the preferred or optimized path.

A unit test for a new helper is insufficient if callers can still bypass it and make their own decisions.

Likewise, a passing integration test for one execution mode does not establish correctness in other affected modes.

Prefer tests that make future divergence observable: for example, tests that exercise multiple callers against the same rule, compare required equivalent behavior across modes, or verify that a known edge case has the same intended interpretation everywhere.

Tests should validate the real implementation and its integration. Do not add artificial test-only duplication or merely assert that the source contains a desired helper name.

**Read that last sentence as forbidding the brittle form, not the
architectural one.** These are different tests:

- *"the source mentions `_validate_c_flag`"* -- brittle, and it says
  nothing: a file can mention the helper once and still implement the
  rule locally nine other times. Forbidden.
- *"every site that applies this decision routes through
  `_validate_c_flag`, and the check precedes the operation it guards"*
  -- this is the **architecture test** this policy needs. It is what
  makes the invariant hold as the code changes, and it fails the
  moment a twenty-ninth local implementation appears.

Where the policy's invariant is "there is exactly one authoritative
implementation", the test must be able to observe that. Asserting the
architecture is not asserting a name; it is asserting the property
the policy is about. `python/tests/test_helper_death_excuse.py` is the
worked example: it asserts that every helper-death site asks the
shared decision, and that the consult precedes the abort in its block.
Both assertions are mutation-checked -- unwiring one site fails the
first, moving one consult after its abort fails the second.

## 7. Mandatory self-review before declaring a change complete

After implementing a change, perform a focused SSoT audit of the diff and the affected code.

Answer these questions:

1. What specific correctness-critical decisions did this change introduce or modify?
2. For each decision, where is its single authoritative implementation?
3. Did I add a new conditional, helper, exception handler, state transition, or fallback branch that independently implements an existing rule?
4. Are any affected callers still making the same decision locally rather than delegating to the authoritative implementation?
5. Do apparent differences between execution paths represent genuinely different semantics, or merely historical drift?
6. Are the exceptional cases centralized, or did I centralize only the happy path?
7. For each centralized decision, is the **order** of operations inside it also correct -- does a check that reads state another step produces come *before* that step (section 4.1)?
8. Do tests demonstrate both correct decision-making and use of the authoritative implementation by affected callers?
9. Did the change inadvertently preserve obsolete implementations or create a new source of truth?
10. Have I searched the relevant execution modes and call sites for equivalent logic, rather than relying solely on the files I edited?

Use repository searches, diff inspection, and relevant tests to answer these questions. Do not treat the absence of identical text as proof that no semantic duplication exists.

If a duplicate decision is discovered, resolve it as part of the change whenever its scope permits. Do not knowingly defer it to a later deduplication pass simply because the immediate functionality works.

If an existing duplicate is outside the change's safe scope, identify it explicitly, explain the risk, and record the remaining work instead of silently treating the new implementation as authoritative.

## 8. Required implementation behavior for AI-generated changes

When generating code:

- Prefer extending existing authoritative logic over creating new policy-bearing code.
- Investigate before adding a helper that makes a correctness-sensitive choice.
- Do not independently reproduce another function's decision logic and assume future developers will keep the implementations synchronized.
- Do not use a new execution mode, class, module, or optimization path as justification for duplicating a shared decision.
- Do not declare a task complete solely because the new path passes its tests.
- Do not perform a superficial deduplication that leaves the underlying decision distributed across callers.
- Do not refactor unrelated code merely to maximize abstraction or minimize line counts.

When a task explicitly requests a new implementation, first establish whether the requested implementation is actually a new policy or only a new consumer of an existing policy. Preserve a single authoritative decision either way.

When the correct architecture is uncertain, investigate the existing contracts and behavior before choosing an implementation. Where ambiguity remains consequential, state the unresolved semantic question rather than silently introducing another competing policy.

## 9. Completion report

For any substantial correctness-sensitive change, include a concise SSoT summary in the implementation report:

- **Decision(s) affected:** What correctness-critical rules changed?
- **Authoritative implementation:** Where does each rule now live?
- **Consumers:** Which callers or execution paths use it?
- **Duplication eliminated or avoided:** Which competing implementations were removed, reused, or not introduced?
- **Intentional differences:** What similar logic remains separate, and why is it semantically distinct?
- **Divergence resolved:** Where copies had drifted, which behaviour won, and where is it tested?
- **Order:** For a decision whose correctness depends on the order of operations, what enforces it?
- **Verification:** Which targeted and integration tests were run, and what did they establish?
- **Residual concerns:** What relevant paths, tests, or existing duplications remain unverified or unresolved?

Report actual evidence. Distinguish tests that were run from tests that are merely planned, and distinguish paths that were inspected from paths that were not inspected.

## 10. Definition of done

A change satisfies this policy only when each correctness-critical decision it introduces or modifies has one identifiable authoritative implementation, affected callers reuse that implementation, genuine semantic differences are explicit, and appropriate tests establish both correctness and integration.

**The governing principle is simple: one logical correctness-critical decision, one authoritative implementation, any number of consumers.**

Single Source of Truth is an architectural correctness property. It must be established during initial implementation, preserved during subsequent changes, and verified during review—not deferred to a cleanup pass.

## 11. A worked example: a rule wired into 2 of 28

This is the case that motivated the policy, in this repository's own
history, because the numbers are what make the rule concrete.

**The rule.** A helper child -- a scanner, a drain, an orderer, a
reaper -- dying is *expected* when an abort is already in flight: the
child died as the abort's consequence, and re-aborting would print a
spurious FATAL and clobber the abort's own outcome. D-PORT2/D6
introduced that classification -- "an abort already in flight makes
helper deaths expected (emergency path), not fatal" -- and wired it
into the helper watchers.

**What actually happened.** The front end applies that rule in **28**
places: every site that turns a helper child's non-zero exit into a
fatal error. The fix was wired into **2** of them.

The other 26 were not overlooked by a careless author. They are the
same rule written out **inline**, in the body of each executor, and a
function-level duplicate scan found almost none of them -- inline
duplication is invisible to a function-level scan by construction. The
commit's own wording -- "both UMA scanner watches" -- shows the author
believed there were two.

**The consequence.** Any change to that rule had to be made in 28
places, and the one change that was made reached two. Meanwhile a
second rule of the same kind -- the C drain child's exit, also a helper
child's death -- was consulted in **none** of its 10 places.

**What the fix looks like now.** One decision point:

```python
def _helper_death_excused(kind, eof_ok, lib):
    """Has an abort already explained this helper child's death?"""
    return (_helper_death_disposition(kind, eof_ok,
                                      _abort_reason_now(lib)) == "excuse")
```

and every one of the 24 helper-death raise sites asks it. The
consolidation also **changed behaviour** on the paths that had drifted
-- the NUMA orderer copy, and the ten C-drain copies, now consult the
rule they never consulted. That is the divergence rule (section 3,
step 4) doing its job, not a regression, and it is reported as such.

**And the order matters.** The rule asks whether an abort is in flight,
and the abort's own call publishes the reason the rule reads. A consult
placed *after* the abort therefore always sees "excused" and swallows
every genuine failure. One site had it that way; the test now fails if
the order is inverted, not only if the outcome is wrong.

**The lesson, in one line:** the fix was correct, and it still reached
two places out of twenty-eight -- because the other twenty-six were not
functions.

## 12. Brief Version

**Non-negotiable SSoT rule:** Every specific correctness-critical
decision must have exactly one authoritative implementation. Before
writing new decision logic, search the repository for existing
equivalent logic and reuse or extend its authoritative implementation.
Never create a parallel implementation merely because it is locally
convenient, belongs to another module, or serves another execution mode.
Centralize the shared decision — including relevant edge cases — while
leaving caller-specific actions separate. Repeated invocations of one
shared rule are acceptable; independently implemented copies of that
rule are not.

**When copies have drifted, the divergence is the defect.** Resolve it
in favour of one implementation, say which behaviour won, and test it.
Do not preserve a divergent copy "to be safe". The order of operations
inside a centralized decision is part of the decision.

**A critical section is a decision too.** Whoever acquires a resource
must acquire it atomically with the resource, and the release must
survive an interruption that would otherwise abandon it: defer the
interruption across the section (do not swallow it), and do not let it
replace an exception that is already propagating. One authoritative
registry for acquisitions; one authoritative primitive for deferring
interruptions.

**Before declaring a change complete:** inspect the diff and the
relevant call sites for semantic duplication, verify that the affected
callers use the authoritative implementation, and run tests covering
both the decision and its integration. Do not defer known duplication to
a later cleanup pass. Report the authoritative implementation, the
affected callers, the intentional differences, the resolved divergence,
the tests actually run, and the unresolved concerns.

**Scope:** this governs the decisions a change introduces, modifies, or relies on — it is not a licence to audit the tree, and a change that adds no correctness-critical decision needs no SSoT work.

**How to search:** `tools/ssot_scan.py` compares statement **blocks**, not function bodies. A decision duplicated inline is invisible to a function-level scan — the abort-aware helper-death rule was applied in 28 places, and a function-level scan found almost none of them.

**How to enforce:** an architecture test that asserts every site routes through the authoritative implementation is required; asserting that the source merely *mentions* a helper name is not.

See dev/supervisor/SSoT.md for the full version.
