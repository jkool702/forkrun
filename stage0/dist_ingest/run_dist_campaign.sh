#!/usr/bin/env bash
# One-command comparative campaign for distributed-ingestion prototypes.
# Section 5 comparability: runs centralized_ingest (dist-engine control) and
# fixed_faa / local_adaptive / relative_adaptive on the SAME experimental engine,
# consumer implementation, work units, and measurement boundaries.
# production_ref (optional) runs existing forkrun path as SEPARATE reference only
# (not apples-to-apples vs dist_ingest engine).
# across defined scenarios. Immutable output directory, raw artifacts kept.
#
# No physical hardware rental. Fake NUMA / local only.
set -u
cd "$(dirname "$0")/../.."

usage() {
  cat <<'EOF'
usage: run_dist_campaign.sh [options]
  --out DIR            campaign directory (must be absent/empty)
  --campaign-id ID     unique id
  --trials N           trials per case (default 3)
  --quick              small local smoke (1 trial, small corpus, subset)
  --scenarios LIST     comma-separated scenario ids (default: all)
  --candidates LIST    comma-separated (default: centralized_ingest,fixed_faa,local_adaptive,relative_adaptive)
  --source-sha SHA
  --seed SEED          deterministic random seed for candidate/scenario ordering
  --shuffle-scenarios  randomize scenario-block order (reproducible by seed)
  --cache-policy TEXT  explicit cache/warm-up assumption recorded in manifest
EOF
}

TRIALS=${TRIALS:-3}
OUT=""
CAMPAIGN_ID=""
SOURCE_SHA=""
QUICK=0
SCEN_FILTER=""
CAND_FILTER="centralized_ingest,fixed_faa,local_adaptive,relative_adaptive"
SEED=""
SHUFFLE_SCENARIOS=0
CACHE_POLICY="best_effort_os_cache (no privileged cold-cache control; limitation explicit)"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --out) OUT=${2:?}; shift 2 ;;
    --campaign-id) CAMPAIGN_ID=${2:?}; shift 2 ;;
    --trials) TRIALS=${2:?}; shift 2 ;;
    --quick) QUICK=1; TRIALS=1; shift ;;
    --scenarios) SCEN_FILTER=${2:?}; shift 2 ;;
    --candidates) CAND_FILTER=${2:?}; shift 2 ;;
    --source-sha) SOURCE_SHA=${2:?}; shift 2 ;;
    --seed) SEED=${2:?}; shift 2 ;;
    --shuffle-scenarios) SHUFFLE_SCENARIOS=1; shift ;;
    --cache-policy) CACHE_POLICY=${2:?}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "dist-campaign: unknown arg $1" >&2; exit 2 ;;
  esac
done

if [ -z "$SOURCE_SHA" ]; then
  SOURCE_SHA=$(git rev-parse HEAD) || { echo "dist-campaign: cannot resolve HEAD" >&2; exit 2; }
fi
if [ -z "$CAMPAIGN_ID" ]; then
  CAMPAIGN_ID="dist-$(date -u +%Y%m%dT%H%M%SZ)-${SOURCE_SHA:0:12}-$$"
fi
if [ -z "$OUT" ]; then
  OUT="stage0/dist_ingest/runs/$CAMPAIGN_ID"
fi
if [ -z "$SEED" ]; then
  # deterministic default seed recorded for reproducibility
  SEED="$CAMPAIGN_ID"
fi

if [ -e "$OUT" ]; then
  if [ ! -d "$OUT" ] || [ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo "dist-campaign: output not empty/absent: $OUT" >&2; exit 2
  fi
fi
mkdir -p "$OUT/cases" "$OUT/env" "$OUT/corpora" || exit 1

export FORKRUN_DIAG_QUEUE=1

echo "=== dist-ingest campaign: build"
make -f Makefile.substrate python-substrate >/dev/null 2>&1 || echo "WARN: python-substrate build issue (continuing)"
(cd stage0/dist_ingest && make) || { echo "dist-campaign: dist_ingest build failed" >&2; exit 1; }

echo "=== dist-ingest campaign: environment"
python3 stage0/env_capture.py --out "$OUT/env/env-before.json" --run-id "$CAMPAIGN_ID" \
  || { echo "dist-campaign: env-before failed" >&2; exit 1; }

echo "=== dist-ingest campaign: corpora"
# Deterministic corpora for scenarios (file ingestion first).
python3 - "$OUT" "$QUICK" <<'PY'
import os, sys
out, quick = sys.argv[1], sys.argv[2] == '1'
os.makedirs(os.path.join(out,'corpora'), exist_ok=True)
def make(path, size):
    if os.path.exists(path): return
    with open(path,'wb') as f:
        chunk = b'abcdefghij' * 102400  # 1MB-ish pattern
        rem = size
        while rem > 0:
            n = min(rem, len(chunk))
            f.write(chunk[:n]); rem -= n
if quick:
    make(os.path.join(out,'corpora','large.bin'), 32*1024*1024)
    make(os.path.join(out,'corpora','small.bin'), 1024*1024)
    make(os.path.join(out,'corpora','tiny.bin'), 4096)
else:
    make(os.path.join(out,'corpora','large.bin'), 256*1024*1024)
    make(os.path.join(out,'corpora','small.bin'), 8*1024*1024)
    make(os.path.join(out,'corpora','tiny.bin'), 4096)
    make(os.path.join(out,'corpora','boundary.bin'), 2*1024*1024 + 1)
    make(os.path.join(out,'corpora','exact2m.bin'), 2*1024*1024)
print('corpora ready')
PY

# Scenario definitions (id|input_rel|nodes|consumer_mode|consumer_bps|slow_node|slow_mode|slow_bps|slow_stall_ms|max_backlog|extra)
# Required scenarios covered: equal/slow/fast/asymmetric consumers, temp stall+recovery,
# varying node counts, large sequential file, small/short-final/boundary, backpressure.
SCENARIOS=()
if [ "$QUICK" -eq 1 ]; then
  SCENARIOS+=("equal|corpora/large.bin|4|fast|0|-1|fast|0|0|33554432|")
  SCENARIOS+=("slow_one|corpora/large.bin|4|fast|0|0|slow|20000000|0|33554432|")
  SCENARIOS+=("stall_recover|corpora/large.bin|4|fast|0|1|stall|0|500|33554432|")
  SCENARIOS+=("small|corpora/small.bin|2|fast|0|-1|fast|0|0|16777216|")
else
  SCENARIOS+=("equal|corpora/large.bin|4|fast|0|-1|fast|0|0|67108864|")
  SCENARIOS+=("slow_one|corpora/large.bin|4|fast|0|0|slow|15000000|0|67108864|")
  SCENARIOS+=("fast_one|corpora/large.bin|4|slow|10000000|1|fast|0|0|67108864|")
  SCENARIOS+=("asymmetric|corpora/large.bin|4|fast|0|0|slow|8000000|0|67108864|")
  SCENARIOS+=("stall_recover|corpora/large.bin|4|fast|0|2|stall|0|800|67108864|")
  SCENARIOS+=("nodes2|corpora/large.bin|2|fast|0|-1|fast|0|0|67108864|")
  SCENARIOS+=("nodes8|corpora/large.bin|8|fast|0|-1|fast|0|0|67108864|")
  SCENARIOS+=("large_seq|corpora/large.bin|4|fast|0|-1|fast|0|0|134217728|")
  SCENARIOS+=("small|corpora/small.bin|2|fast|0|-1|fast|0|0|16777216|")
  SCENARIOS+=("tiny|corpora/tiny.bin|2|fast|0|-1|fast|0|0|4194304|")
  SCENARIOS+=("boundary|corpora/boundary.bin|4|fast|0|-1|fast|0|0|33554432|")
  SCENARIOS+=("backpressure|corpora/large.bin|4|slow|5000000|-1|slow|5000000|0|8388608|")
fi

IFS=',' read -ra CANDS <<< "$CAND_FILTER"
FAILURES=()
OUTCOMES="$OUT/.outcomes.tsv"
ORDER_LOG="$OUT/execution-order.jsonl"
: > "$OUTCOMES"
: > "$ORDER_LOG"

# Build and execute randomized/interleaved plan (Section 7). Candidate order is
# shuffled within each (scenario,trial) block; scenario-block order optionally
# shuffled. Seed and actual execution order recorded for reproducibility.
PLAN_FILE="$OUT/.run_plan.tsv"
export DIST_SCEN_DEFS="$(printf '%s\n' "${SCENARIOS[@]}")"
python3 - "$OUT" "$SEED" "$TRIALS" "$SCEN_FILTER" "$CAND_FILTER" "$SHUFFLE_SCENARIOS" "$PLAN_FILE" <<'PY'
import json, os, random, sys
out, seed, trials, scen_filter, cand_filter, shuf_sc, plan_path = sys.argv[1:8]
trials = int(trials)
shuf_sc = shuf_sc == '1'
scen_defs = [l for l in os.environ.get('DIST_SCEN_DEFS','').split('\n') if l.strip()]
scen_set = set([s for s in scen_filter.split(',') if s]) if scen_filter else None
cand_list = [c for c in cand_filter.split(',') if c]
def allowed_scen(s): return scen_set is None or s in scen_set
scens = []
for d in scen_defs:
    sid = d.split('|',1)[0]
    if allowed_scen(sid): scens.append(d)
rng_scen = random.Random(str(seed) + '|scenarios')
if shuf_sc:
    rng_scen.shuffle(scens)
blocks = []
for d in scens:
    sid = d.split('|',1)[0]
    for t in range(1, trials+1):
        cands = list(cand_list)
        random.Random(str(seed)+'|'+sid+'|'+str(t)).shuffle(cands)
        blocks.append((sid,d,t,cands))
with open(plan_path,'w') as f:
    for sid,d,t,cands in blocks:
        f.write('\t'.join([sid,d,str(t),','.join(cands)])+'\n')
# record plan summary
with open(os.path.join(out,'execution-plan.json'),'w') as f:
    json.dump({'seed':seed,'shuffle_scenarios':shuf_sc,'trials':trials,
               'scenarios':[b[0] for b in blocks if b[2]==1] if shuf_sc else [d.split('|',1)[0] for d in scens],
               'blocks':[{'scenario':b[0],'trial':b[2],'candidate_order':b[3]} for b in blocks]}, f, indent=2, sort_keys=True)
PY

while IFS=$'\t' read -r sid scen_def t cand_csv; do
  [ -z "$sid" ] && continue
  IFS='|' read -r _sid inp nodes cmode cbps snode smode sbps sstall mbacklog extra <<< "$scen_def"
  IFS=',' read -ra BLOCK_CANDS <<< "$cand_csv"
  echo "BLOCK scenario=$sid trial=$t order=$cand_csv" >&2
  printf '{"scenario":"%s","trial":%s,"candidate_order":[%s]}\n' "$sid" "$t" "$(python3 - <<PY "$cand_csv"
import json,sys; print(','.join(json.dumps(x) for x in sys.argv[1].split(',') if x))
PY
)" >> "$ORDER_LOG"
  for cand in "${BLOCK_CANDS[@]}"; do
    [ -z "$cand" ] && continue
    case_id="${sid}__${cand}"
    out="$OUT/cases/$case_id/trial$t"
    # Re-running a failed block must not overwrite earlier raw evidence.
    if [ -e "$out/manifest.json" ]; then
      echo "SKIP existing evidence: $case_id trial$t" >&2
      prev=skipped_existing
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$case_id" "$sid" "$cand" "$t" "$prev" "cases/$case_id/trial$t/manifest.json" >> "$OUTCOMES"
      continue
    fi
    mkdir -p "$out" || exit 1
    spec="$out/spec.json"
    input_path="$OUT/$inp"
    # build spec
    python3 - "$spec" "$sid" "$cand" "$case_id" "$input_path" "$nodes" "$cmode" "$cbps" "$snode" "$smode" "$sbps" "$sstall" "$mbacklog" "$SEED" <<'PY'
import json, sys
(spec,sid,cand,cid,inp,nodes,cmode,cbps,snode,smode,sbps,sstall,mbacklog,seed)=sys.argv[1:15]
d={
  "id": cid,
  "scenario": sid,
  "input": inp,
  "timeout": 600,
  "campaign_seed": seed,
}
if cand in ("production_ref", "forkrun_control"):
  d.update({
    "mode": "udf",
    "workers": max(2, int(nodes)),
    "nodes": "auto" if int(nodes) > 1 else "1",
    "candidate": cand,
    "reference_only": True,
  })
elif cand == "control":
  d.update({
    "mode": "udf",
    "workers": max(2, int(nodes)),
    "nodes": "auto" if int(nodes) > 1 else "1",
    "candidate": "production_ref",
    "reference_only": True,
  })
else:
  d.update({
    "ingest_candidate": cand,
    "dist_nodes": int(nodes),
    "base_quantum": 2*1024*1024,
    "max_backlog": int(mbacklog),
    "consumer_mode": cmode,
    "consumer_bps": int(cbps),
    "slow_node": int(snode),
    "slow_mode": smode,
    "slow_bps": int(sbps),
    "slow_stall_ms": int(sstall),
  })
with open(spec,'w') as f: json.dump(d,f,indent=2,sort_keys=True)
PY
    if python3 stage0/run_case.py --spec "$spec" --out "$out" \
         --campaign-id "$CAMPAIGN_ID" --trial "$t" --source-sha "$SOURCE_SHA"; then
      status=ok
    else
      status=failed
      FAILURES+=("$case_id trial$t")
      echo "TRIAL FAILED: $case_id trial$t" >&2
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$case_id" "$sid" "$cand" "$t" "$status" "cases/$case_id/trial$t/manifest.json" >> "$OUTCOMES"
  done
done < "$PLAN_FILE"

python3 stage0/env_capture.py --out "$OUT/env/env-after.json" --run-id "$CAMPAIGN_ID" \
  || echo "WARN: env-after capture failed" >&2

# campaign manifest (Section 7: seed, actual execution order, cache assumptions)
python3 - "$OUT" "$CAMPAIGN_ID" "$SOURCE_SHA" "$TRIALS" "$OUTCOMES" "$SEED" "$CACHE_POLICY" "$SHUFFLE_SCENARIOS" <<'PY'
import json, os, sys, time
out,cid,sha,trials,outcomes,seed,cache_policy,shuf_sc=sys.argv[1:9]
rows=[]
with open(outcomes) as f:
    for line in f:
        line=line.rstrip('\n')
        if not line: continue
        case,scen,cand,t,status,man=line.split('\t')
        rows.append({"case":case,"scenario":scen,"candidate":cand,"trial":int(t),"status":status,"manifest":man})
order=[]
op=os.path.join(out,'execution-order.jsonl')
if os.path.isfile(op):
    with open(op) as f:
        for line in f:
            line=line.strip()
            if line: order.append(json.loads(line))
plan=None
pp=os.path.join(out,'execution-plan.json')
if os.path.isfile(pp):
    with open(pp) as f: plan=json.load(f)
all_ok = all(r['status'] in ('ok','skipped_existing') for r in rows) if rows else False
doc={"schema":"dist-campaign/2","campaign_id":cid,"source_sha":sha,"trials":int(trials),
     "randomization":{"seed":seed,"shuffle_scenarios":(shuf_sc=='1'),"execution_order":order,"plan":plan},
     "cache_policy":cache_policy,
     "outcomes":rows,"all_ok":all_ok,"finished_epoch":time.time()}
with open(os.path.join(out,'campaign-manifest.json'),'w') as f: json.dump(doc,f,indent=2,sort_keys=True)
PY

echo "=== dist-ingest campaign: report"
python3 stage0/dist_ingest/report_dist.py --campaign "$OUT" --out "$OUT/report.md" || echo "WARN: report generation failed" >&2

if [ "${#FAILURES[@]}" -gt 0 ]; then
  echo "dist-campaign: ${#FAILURES[@]} trial(s) failed" >&2
  printf '  - %s\n' "${FAILURES[@]}" >&2
  echo "manifest: $OUT/campaign-manifest.json" >&2
  exit 1
fi
echo "dist-campaign complete: $OUT"
