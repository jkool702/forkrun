# Mandatory Engineering Policy: Single Source of Truth (SSoT)

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

## 7. Mandatory self-review before declaring a change complete

After implementing a change, perform a focused SSoT audit of the diff and the affected code.

Answer these questions:

1. What specific correctness-critical decisions did this change introduce or modify?
2. For each decision, where is its single authoritative implementation?
3. Did I add a new conditional, helper, exception handler, state transition, or fallback branch that independently implements an existing rule?
4. Are any affected callers still making the same decision locally rather than delegating to the authoritative implementation?
5. Do apparent differences between execution paths represent genuinely different semantics, or merely historical drift?
6. Are the exceptional cases centralized, or did I centralize only the happy path?
7. Do tests demonstrate both correct decision-making and use of the authoritative implementation by affected callers?
8. Did the change inadvertently preserve obsolete implementations or create a new source of truth?
9. Have I searched the relevant execution modes and call sites for equivalent logic, rather than relying solely on the files I edited?

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
- **Verification:** Which targeted and integration tests were run, and what did they establish?
- **Residual concerns:** What relevant paths, tests, or existing duplications remain unverified or unresolved?

Report actual evidence. Distinguish tests that were run from tests that are merely planned, and distinguish paths that were inspected from paths that were not inspected.

## 10. Definition of done

A change satisfies this policy only when each correctness-critical decision it introduces or modifies has one identifiable authoritative implementation, affected callers reuse that implementation, genuine semantic differences are explicit, and appropriate tests establish both correctness and integration.

**The governing principle is simple: one logical correctness-critical decision, one authoritative implementation, any number of consumers.**

Single Source of Truth is an architectural correctness property. It must be established during initial implementation, preserved during subsequent changes, and verified during review—not deferred to a cleanup pass.

## 11. Brief Version

**Non-negotiable SSoT rule:** Every specific correctness-critical decision must have exactly one authoritative implementation. Before writing new decision logic, search the repository for existing equivalent logic and reuse or extend its authoritative implementation. Never create a parallel implementation merely because it is locally convenient, belongs to another module, or serves another execution mode. Centralize the shared decision—including relevant edge cases—while leaving caller-specific actions separate. Repeated invocations of one shared rule are acceptable; independently implemented copies of that rule are not. Preserve separate implementations only when their semantics are genuinely different, and document and test that distinction. Before declaring a change complete, inspect the diff and relevant call sites for semantic duplication, verify that affected callers use the authoritative implementation, and run tests covering the decision and its integration. Do not defer known duplication to a later cleanup pass. Report the authoritative implementation, affected callers, intentional differences, tests actually run, and unresolved concerns.

See dev/supervisor/SSoT.md for the full version.
