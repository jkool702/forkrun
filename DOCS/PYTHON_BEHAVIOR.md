# forkrun Python frontend — behavioral notes

Frontend contracts that are not derivable from `INVARIANTS.md` (which
states the engine laws) or from the Bash frontend (which has no Python
equivalent for these).

**Provenance.** This content previously existed ONLY inside the generated
aggregate `DOCS/DOCS_ALL.md`, with no source document owning it. That is
exactly the drift `tools/gen_docs_all.py --check` exists to prevent, so
the content was given a home here rather than deleted when the
aggregate started being regenerated from sources.

### W-REL5-B: Python behavioral correctness (behavioral notes)

- `sink=` ownership: only `run()` owns a worker-side sink. The
  collecting frontends (`map`/`stream`/`sweep`) reject it loudly
  instead of ignoring it — the payload return value is the result
  there, and a second result channel would be a silent-drop trap.
- Stream taxonomy is uniform now: `SIGINT` during `stream()`
  iteration raises `ForkrunInterrupted` (catchable as either
  `forkrun.ForkrunInterrupted` or `KeyboardInterrupt`), exactly
  like the blocking paths.
- Ingest-reactor liveness: the spill supervises (death pipes,
  trap-ACK deadlines, stall fork) per quantum even when the
  source yields nothing for seconds. A pre-gate SIGKILL that
  lands mid-claim still aborts loudly (claim-without-publish
  race, rc==4) — observation is prompt; attribution limits are
  engine semantics, unchanged by this wave.
- Helper joins are bounded (10s; orderer 10s via
  `ORDERER_REAP_TIMEOUT`; post-abort worker reaps 3s via
  `WORKER_REAP_TIMEOUT`) with a naming alarm; worker completion
  joins are unbounded by design.
- `reactor_poll_once` blocks at most `poll_timeout` plus a
  bounded 0.5s death-confirm spin; longer absences mean the
  child is alive, not that the poll hung.
- Worker-failure `RuntimeError`s carry `.signo` (first signal
  death or `None`); the class contract is unchanged (signal
  causes with taxonomy classes, engine faults plain
  `RuntimeError`).
