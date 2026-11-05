# Round 18 — two questions before I touch the ring

Branch `NEW/REFACTOR4.2`, head `a1505bee`. Short by design: round 17's
direction is unchanged and I am not re-litigating it. **Two decisions in
the plan changed after you reviewed it, and both are load-bearing.**

---

## 1. The counting site moved — and that shrinks the ring exception

Round 17 endorsed incrementing at the successful order-packet submission
site (`fr_py_ack_core`, `_shim.c:3108`). Before implementing I read the
emit path, and **that site cannot count frames**, for two reasons:

- **Granularity.** One packet covers *every* record appended since the
  last ack (`op.len = curr - last_ack_offset`), so one packet may carry
  several frames.
- **Disposition is invisible there.** `fr_py_emit` (`_shim.c:907`) sets
  `hdr.disposition = (src_len == 0) ? FR_DISP_NO_RESULT : FR_DISP_DATA`,
  and the framer **filters** non-`DATA` frames. So a packet with
  `op.len > 0` can carry a NO_RESULT the parent never observes — counting
  it mismatches on any healthy run that emitted `None` or `b""`, which is
  precisely the case C0.5's "None vs `b''`" test pins.

**Revised site: `fr_py_emit`, once per `FR_DISP_DATA` record, after
`fr_py_write_all` succeeds.** Per-frame, disposition available, post-write.

**The useful consequence: `fr_py_emit` is in the shim.** So the increment
is *not* a ring change. Only the `SharedState` field is — which is a
strictly smaller frozen-ring exception than the one you authorized.

> **Question 1: does the revised site satisfy your invariant?** Namely:
> *every DATA record a worker emitted was observed as a frame by the
> parent.* I believe this is strictly better than the submission count —
> it detects loss between emit and collection, which the submission count
> also did, and additionally does not overcount filtered dispositions.

> **Question 2: is excluding `ring_ack_main` (`forkrun_ring.c:6934`)
> correct?** It has a parallel packet write on the non-Python worker path.
> I intend to leave it uninstrumented and document the Python
> certificate's envelope as excluding it, rather than instrumenting two
> producers and risking double-counting.

## 2. Also recorded, because it surprised me

The comment immediately above `_shim.c:907` says *"a real empty DATA
result is carried as DATA with len == 0"*. The next line does the
opposite: `src_len == 0 → NO_RESULT`.

**Pre-existing doc/code contradiction, which I have NOT fixed** — the
counter design depends on which is true and the code is what runs. Flagged
because your `#2` said "test both a legitimate empty result and a
no-result value", and on this code **both map to NO_RESULT**, so the
"legitimate empty result" case may not be constructible as written.

> Is that intentional, or a separate defect to log?

---

## Not asking about (already adopted from round 17)

`__atomic_fetch_add(..., RELAXED)` not a release store; shim-side accessor
rather than enlarging the six-element diagnostic; field appended at the
**end** of `SharedState`; snapshot requires producer **quiescence** (a
lifecycle guarantee, not stronger ordering); counter named for what it
counts rather than for scanner slots.

## While you consider this

I can do the ring-free required work tonight: the **fault-injection
harness** (your gate 2) with frame-dropping in the framer, which is
shim/Python-side and touches nothing frozen. If the answers move the
design, that work is still needed either way.

Nothing in the ring has been touched. 1065 tests green.