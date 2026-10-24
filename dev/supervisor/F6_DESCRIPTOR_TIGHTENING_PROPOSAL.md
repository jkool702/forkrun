# F6 Descriptor Tightening — PROPOSAL ONLY

**Status: PROPOSAL. Not implemented, not authorised, not scheduled.**

This document exists because the equivalence-first policy deliberately left
one question open, and closing F6 without answering it would be misleading.
It is written so a reviewer can decide whether the work is worth doing, not
so it can be done.

Nothing in this file is implemented. `python/forkrun/run.py` contains no
descriptor tightening: `closefrom` and `close_fds` appear nowhere in it,
and `grep -c 'closefrom\|close_fds' python/forkrun/run.py` is `0`.

---

## 1. The question

F6 adopted `posix_spawn` as the default cleanroom launch backend under an
**equivalence-first** policy: reproduce the post-exec descriptor set the
shipped `fork()+execv()` produced, *including* descriptors that leak.

That policy is deliberate and was the right call for a default switch. It
means adopting the new backend cannot change what a caller observes, so the
switch needed no compatibility argument. The cost is that an **inheritable,
unrelated descriptor in the parent still reaches the launcher**, which is
both an isolation weakness and a latent fd leak.

`CLEANROOM_FD_CONTRACT.md` §5 states this and
`test_equivalence_is_not_isolation` asserts it on both backends.

## 2. Why it is a proposal and not a bug

The leak is **pre-existing and backend-independent**. It is not something
the `posix_spawn` switch introduced, and fixing it is not required to make
that switch safe. It is a behaviour change, which is exactly what the
equivalence-first policy was constructed to avoid during a default switch.

Tightening would make `posix_spawn` and `forkexec` **differ** in the
descriptor set they produce, which is the opposite of the property F6 spent
three stages establishing. It therefore needs its own evidence, its own
approval and its own tests.

## 3. What tightening would mean

The launcher currently inherits every inheritable descriptor the parent
happens to hold. Tightening would restrict it to the route's own:

- `--src` (source)
- `--result` (result memfd, or the streaming pipe write end)
- `--stats-fd` (counter/poison channel; the launcher publishes this as
  `FRK_POISON_FD` for its workers)
- `--trace-fd` when `FORKRUN_CLEANROOM_TRACE` is set
- fd 2, which is the captured launcher-stderr channel
- whatever the UDF helper genuinely needs

and nothing else.

Mechanically, with `posix_spawn` this is a `POSIX_SPAWN_CLOSE` action per
descriptor, or `closefrom` semantics; `test_explicit_close_action_removes_the_unrelated_descriptor`
already shows the single-close form works. The difficulty is not the
mechanism, it is deciding the **policy**, and the `forkexec` arm, where
there is no `file_actions` and the child would need an explicit loop.

## 4. Compatibility implications to analyse before implementing

1. **Callers that pass descriptors deliberately.** A caller who opens a fd
   with `os.set_inheritable(fd, True)` and relies on it reaching the
   launcher, or a worker, would break. Is that supported today? Nothing in
   the public API documents it, but "undocumented" is not "unsupported".
2. **The UDF helper path.** `_fr_udf*.so` and its version handshake must
   still work with only the listed descriptors.
3. **Backends would diverge.** Either tightening applies to `forkexec` too
   (an explicit close loop in the child, which reintroduces Python-level
   work between fork and exec — the very thing that is unsafe in a
   multithreaded parent), or the two backends differ in observable
   descriptor state, which weakens the equivalence property F6 relies on
   for bisecting a regression.
4. **Ordering.** Descriptor-closing actions run in order at the specified
   point; getting them wrong can close the error channel and turn a clear
   failure into silence.

## 5. Tests that would be required

- The unrelated inheritable descriptor is absent at launcher `main()`
  entry, observed by the existing `-DFORKRUN_ENTRY_FD_PROBE` harness,
  for **both** shapes and **both** backends.
- The route's own descriptors are still present and still inheritable.
- `FRK_POISON_FD` still equals `--stats-fd`.
- fd 2 still carries the captured error channel.
- A caller-supplied descriptor that the launcher must *not* see is gone;
  one it must see is present.
- Repeated launches and both leak tests stay green.

## 6. Migration risk

Low for library users who do not deliberately pass inheritable descriptors.
Non-zero for a caller that does, and that class is undocumented, so it
cannot be sized from the codebase. A deprecation step — warn when an
unrelated inheritable descriptor is dropped — would be the careful version.

## 7. Open decisions

1. Is deliberate inheritable-descriptor passthrough supported today, or
   merely possible?
2. Does tightening apply to `forkexec` too, accepting a close loop between
   fork and exec, or do the backends diverge?
3. Warn-and-deprecate, or a clean break in a major version?

## 8. Recommendation

Do not bundle this with F6. F6's remaining value is that it is *finished
and verifiable*; attaching a behaviour change to it makes the default
switch harder to review and gives a reviewer two things to reject at once.
Treat it as a separate proposal with its own work order, after the
`forkexec` fallback has served its purpose as a bisection tool.
