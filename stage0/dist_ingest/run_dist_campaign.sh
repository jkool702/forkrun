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
  --out DIR                campaign directory (must be absent/empty)
  --campaign-id ID         unique id
  --trials N               trials per case (default 3)
  --quick                  small local smoke (1 trial, small corpus, subset)
  --scenarios LIST         comma-separated scenario ids (default: all in selected profile)
  --profile NAME           scenario profile: nodes2|nodes4|full (sets --scenarios unless explicit)
  --mapping-profiles LIST  mapping profiles per scenario: auto (legacy, default),
                           cross_socket_spread,intra_socket,all_nodes,explicit,matrix
                           (matrix => all applicable supported among cross_socket_spread,intra_socket,all_nodes)
  --candidates LIST        comma-separated (default: centralized_ingest,fixed_faa,local_adaptive,relative_adaptive)
  --source-sha SHA
  --seed SEED              deterministic random seed for candidate/scenario ordering
  --shuffle-scenarios      randomize scenario-block order (reproducible by seed)
  --cache-policy TEXT      explicit cache/warm-up assumption recorded in manifest
  --consumer-kernel K      full_byte_scan (default) or none (explicit diagnostic opt-out)
  --strict-affinity        require verified affinity for all required roles (abort on failure)
  --strict-mbind           require successful mbind policy application (abort on failure)
  --phys-nodes LIST        explicit physical NUMA node ids (comma-separated). Backward-compatible
                           global explicit mapping override (all selected scenarios must share
                           the same logical node count). For mixed-count mappings use
                           --mapping-profiles (profile-based expansion).
  --plan-only              validate/generate complete plan and exit before builds/corpora/trials
  --dry-run                alias for --plan-only
EOF
}

TRIALS=${TRIALS:-3}
OUT=""
CAMPAIGN_ID=""
SOURCE_SHA=""
QUICK=0
SCEN_FILTER=""
SCEN_FILTER_EXPLICIT=0
PROFILE=""
MAPPING_PROFILES="auto"
CAND_FILTER="centralized_ingest,fixed_faa,local_adaptive,relative_adaptive"
SEED=""
SHUFFLE_SCENARIOS=0
CACHE_POLICY="best_effort_os_cache (no privileged cold-cache control; limitation explicit)"
CONSUMER_KERNEL="full_byte_scan"
STRICT_AFFINITY=0
STRICT_MBIND=0
PHYS_NODES=""
PLAN_ONLY=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --out) OUT=${2:?}; shift 2 ;;
    --campaign-id) CAMPAIGN_ID=${2:?}; shift 2 ;;
    --trials) TRIALS=${2:?}; shift 2 ;;
    --quick) QUICK=1; TRIALS=1; shift ;;
    --scenarios) SCEN_FILTER=${2:?}; SCEN_FILTER_EXPLICIT=1; shift 2 ;;
    --profile) PROFILE=${2:?}; shift 2 ;;
    --mapping-profiles) MAPPING_PROFILES=${2:?}; shift 2 ;;
    --candidates)
      [ "$#" -ge 2 ] || { echo "dist-campaign: --candidates requires an argument" >&2; exit 2; }
      CAND_FILTER=$2; shift 2 ;;
    --source-sha) SOURCE_SHA=${2:?}; shift 2 ;;
    --seed) SEED=${2:?}; shift 2 ;;
    --shuffle-scenarios) SHUFFLE_SCENARIOS=1; shift ;;
    --cache-policy) CACHE_POLICY=${2:?}; shift 2 ;;
    --consumer-kernel) CONSUMER_KERNEL=${2:?}; shift 2 ;;
    --strict-affinity) STRICT_AFFINITY=1; shift ;;
    --strict-mbind) STRICT_MBIND=1; shift ;;
    --phys-nodes) PHYS_NODES=${2:?}; shift 2 ;;
    --plan-only|--dry-run) PLAN_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "dist-campaign: unknown arg $1" >&2; exit 2 ;;
  esac
done

# Documented executable scenario profiles (default/non-quick scenario set).
PROFILE_NODES2="nodes2,small,tiny"
PROFILE_NODES4="equal,slow_one,fast_one,asymmetric,stall_recover,nodes2,large_seq,small,tiny,boundary,backpressure"
PROFILE_FULL=""

PROFILE_KIND=""
if [ -n "$PROFILE" ]; then
  case "$PROFILE" in
    nodes2|2|2node|two) PROFILE_KIND="nodes2"; _ps="$PROFILE_NODES2" ;;
    nodes4|4|4node|four) PROFILE_KIND="nodes4"; _ps="$PROFILE_NODES4" ;;
    full|8|8plus|eight) PROFILE_KIND="full"; _ps="$PROFILE_FULL" ;;
    *) echo "dist-campaign: unknown --profile '$PROFILE' (expected nodes2|nodes4|full)" >&2; exit 2 ;;
  esac
  if [ "$SCEN_FILTER_EXPLICIT" -eq 0 ]; then
    SCEN_FILTER="$_ps"
  fi
fi

if [ "$QUICK" -eq 1 ] && { [ "$PROFILE_KIND" = "nodes2" ] || [ "$PROFILE_KIND" = "nodes4" ]; }; then
  echo "dist-campaign: --profile $PROFILE describes the non-quick scenario set and cannot be used with --quick (use --profile full --quick or select quick-compatible scenarios explicitly)" >&2
  exit 2
fi

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
  SEED="$CAMPAIGN_ID"
fi

if [ -e "$OUT" ]; then
  if [ ! -d "$OUT" ] || [ -n "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo "dist-campaign: output not empty/absent: $OUT" >&2; exit 2
  fi
fi
mkdir -p "$OUT/cases" "$OUT/env" "$OUT/corpora" || exit 1

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

echo "=== dist-ingest campaign: topology/scenario pre-validation"
export DIST_SCEN_DEFS="$(printf '%s\n' "${SCENARIOS[@]}")"
PREVAL_FILE="$OUT/prevalidation.json"
python3 - "$OUT" "$SCEN_FILTER" "$PHYS_NODES" "$PROFILE" "$QUICK" "$PREVAL_FILE" "$SCEN_FILTER_EXPLICIT" "$MAPPING_PROFILES" "$TRIALS" "$CAND_FILTER" "$SEED" "$SHUFFLE_SCENARIOS" <<'PY'
import json, os, re, sys
(out, scen_filter, phys_nodes, profile, quick, preval_path,
 scen_filter_explicit, mapping_profiles_arg, trials_arg, cand_filter_arg, seed_arg, shuf_sc_arg) = sys.argv[1:13]
quick = quick == '1'
scen_filter_explicit = scen_filter_explicit == '1'
requested_profile = profile or None
scen_defs = [l for l in os.environ.get('DIST_SCEN_DEFS', '').split('\n') if l.strip()]
available_ids = []
available_by_id = {}
for d in scen_defs:
    parts = d.split('|')
    sid = parts[0]
    available_ids.append(sid)
    try:
        nodes = int(parts[2])
    except Exception:
        nodes = None
    available_by_id[sid] = {'id': sid, 'nodes': nodes, 'def': d}

# Scenario selection
if scen_filter_explicit:
    raw_ids = scen_filter.split(',')
    requested_ids = [s.strip() for s in raw_ids]
    if not requested_ids or any(s == '' for s in requested_ids):
        print("dist-campaign: --scenarios contains empty/malformed scenario id elements", file=sys.stderr)
        print('dist-campaign: scenario/topology validation failed before timed trials: invalid --scenarios list', file=sys.stderr)
        sys.exit(2)
    seen_ids = set()
    dups = []
    for sid in requested_ids:
        if sid in seen_ids and sid not in dups:
            dups.append(sid)
        seen_ids.add(sid)
    if dups:
        print('dist-campaign: scenario/topology validation failed before timed trials: duplicate scenario id(s): %s' % ','.join(dups), file=sys.stderr)
        sys.exit(2)
    unknown = [sid for sid in requested_ids if sid not in available_by_id]
    if unknown:
        for sid in unknown:
            print('dist-campaign: unknown scenario id requested: %s (available in %s mode: %s)' % (
                sid, 'quick' if quick else 'non-quick', ','.join(available_ids)), file=sys.stderr)
        print('dist-campaign: scenario/topology validation failed before timed trials: unknown scenario id(s): %s' % ','.join(unknown), file=sys.stderr)
        sys.exit(2)
    selected = [available_by_id[sid] for sid in requested_ids]
    scenarios_filter_record = ','.join(requested_ids)
else:
    if scen_filter:
        scen_set = set([s.strip() for s in scen_filter.split(',') if s.strip() != ''])
        selected = [available_by_id[sid] for sid in available_ids if sid in scen_set]
        scenarios_filter_record = scen_filter
    else:
        selected = [available_by_id[sid] for sid in available_ids]
        scenarios_filter_record = None

if not selected:
    print("dist-campaign: no scenarios selected (check --scenarios/--profile)", file=sys.stderr)
    sys.exit(2)

selected_ids = [s['id'] for s in selected]
if scen_filter_explicit:
    effective_profile = 'custom'
    profile_overridden = bool(requested_profile)
else:
    profile_overridden = False
    if requested_profile:
        if quick and requested_profile == 'full':
            effective_profile = 'full_quick'
        else:
            effective_profile = requested_profile
    else:
        if (not quick) and selected_ids == available_ids:
            effective_profile = 'full'
        elif quick and selected_ids == available_ids:
            effective_profile = 'quick_default'
        else:
            effective_profile = 'custom'

repo = os.getcwd()
sys.path.insert(0, os.path.join(repo, 'stage0', 'dist_ingest'))
try:
    import run_dist
    import topology as topo_mod
except Exception as e:
    print('dist-campaign: topology validation failed before timed trials: cannot import topology modules: %s' % e, file=sys.stderr)
    sys.exit(2)

# Parse mapping profiles
raw_mp = [p.strip() for p in mapping_profiles_arg.split(',') if p.strip()]
if not raw_mp:
    raw_mp = ['auto']
if phys_nodes and raw_mp == ['auto']:
    # backward-compatible explicit override
    raw_mp = ['explicit']
matrix_mode = ('matrix' in raw_mp or 'all' in raw_mp)
if matrix_mode:
    req_profiles_base = ['cross_socket_spread', 'intra_socket', 'all_nodes']
else:
    req_profiles_base = [p for p in raw_mp if p not in ('matrix', 'all')]
    if not req_profiles_base:
        req_profiles_base = ['auto']

# Discover inventory / usable nodes
inv = None
host_usable_node_ids = []
host_usable_count = 0
topo_discovery_err = None
try:
    inv = run_dist.discover_topology_inventory()
except Exception as e:
    inv = None
try:
    l, p, info, err = run_dist.resolve_topology(999, None, no_pin=False)
    if l:
        host_usable_node_ids = list(l)
        host_usable_count = len(l)
    else:
        usable = info.get('usable_nodes_auto') or []
        host_usable_node_ids = list(usable)
        host_usable_count = len(usable)
        if host_usable_count == 0 and info.get('online_known') is False:
            topo_discovery_err = 'online-node information unknown; cannot validate selected scenario node counts'
        elif host_usable_count == 0:
            topo_discovery_err = '; '.join(err) if err else 'no usable NUMA nodes discovered'
except Exception as e:
    topo_discovery_err = 'topology probe failed: %s' % e

errors = []
selected_counts = sorted({s['nodes'] for s in selected if s['nodes'] is not None})
for s in selected:
    if s['nodes'] is None:
        errors.append("scenario %s has invalid node count" % s['id'])

# Candidate/trial/randomization validation (must fail before timed-trial manifests).
# Use the actual CLI/shell values passed in (not ambient env) so plan-only and
# execution plans are identical.
RECOGNIZED_CANDIDATES = {
    'fixed_faa', 'local_adaptive', 'relative_adaptive',
    'centralized_ingest', 'centralized',
    'production_ref', 'control', 'forkrun_control',
}
_raw_cands = cand_filter_arg.split(',') if cand_filter_arg is not None else []
cand_tokens = [c.strip() for c in _raw_cands]
if len(cand_tokens) == 0 or any(c == '' for c in cand_tokens):
    errors.append('candidate list must be nonempty and must not contain empty/malformed elements')
plan_candidates = []
_seen_cands = set()
_dup_cands = []
_unknown_cands = []
for c in cand_tokens:
    if c == '':
        continue
    if c in _seen_cands:
        if c not in _dup_cands:
            _dup_cands.append(c)
        continue
    _seen_cands.add(c)
    if c not in RECOGNIZED_CANDIDATES:
        _unknown_cands.append(c)
    else:
        plan_candidates.append(c)
if _dup_cands:
    errors.append('duplicate candidate id(s): %s' % ','.join(_dup_cands))
if _unknown_cands:
    errors.append('unknown candidate id(s): %s' % ','.join(_unknown_cands))
if not plan_candidates and not any('candidate' in e for e in errors):
    errors.append('candidate list must be nonempty')

try:
    plan_trials_n = int(trials_arg)
except Exception:
    plan_trials_n = None
    errors.append('invalid --trials value: %r' % (trials_arg,))
if plan_trials_n is not None and plan_trials_n < 1:
    errors.append('--trials must be >= 1 (got %s)' % plan_trials_n)

plan_seed = str(seed_arg) if seed_arg is not None else ''
# shuffle flag passed as shell 0/1
plan_shuffle_scenarios = str(shuf_sc_arg) in ('1', 'true', 'True', 'yes')

mapping_plan = []  # list of concrete mappings to run
unsupported_mappings = []

# Validate/resolve mappings
resolved_explicit_mapping = None
explicit_mapping_validated = False
explicit_ids_input = None
explicit_count_input = None
if 'explicit' in req_profiles_base or phys_nodes:
    if not phys_nodes:
        errors.append('mapping profile explicit requires --phys-nodes')
    else:
        mapping_mode = 'explicit'
        raw_phys = phys_nodes.split(',')
        phys_malformed = False
        phys_parsed = []
        if raw_phys == [''] or phys_nodes.startswith(',') or phys_nodes.endswith(','):
            phys_malformed = True
        if not phys_malformed:
            for tok in raw_phys:
                st = tok.strip()
                if st == '':
                    phys_malformed = True
                    break
                try:
                    phys_parsed.append(int(st))
                except ValueError:
                    phys_malformed = True
                    break
        if phys_malformed:
            errors.append("malformed --phys-nodes list: %r (reject leading/trailing/consecutive commas, empty elements, and non-integer elements)" % phys_nodes)
            explicit_ids_input = None
            explicit_count_input = None
        else:
            explicit_ids_input = list(phys_parsed)
            explicit_count_input = len(phys_parsed)
            # For explicit mapping, all selected scenarios must share one logical node count
            # (single explicit list cannot map differing logical node counts).
            if len(selected_counts) != 1:
                errors.append("explicit --phys-nodes requires all selected scenarios to have the same logical node count; selected counts: %s" % selected_counts)
            else:
                logical_count = selected_counts[0]
                try:
                    lmap, pcpu, tinfo, terr = run_dist.resolve_topology(logical_count, phys_nodes, no_pin=False)
                except Exception as e:
                    lmap, pcpu, tinfo, terr = [], [], {}, ['resolve_topology exception: %s' % e]
                if terr or not lmap:
                    for te in (terr or ['explicit mapping could not be established']):
                        errors.append('explicit physical-node mapping invalid for selected logical node count %d: %s' % (logical_count, te))
                else:
                    resolved_explicit_mapping = list(lmap)
                    explicit_mapping_validated = True
                    explicit_ids_input = list(lmap)  # mapping accepted by preflight (same as trials will resolve)
                    explicit_count_input = len(lmap)
                    prov_m = None
                    try:
                        invx = run_dist.discover_topology_inventory()
                        prov_m = topo_mod.build_mapping_provenance(invx or {}, 'explicit', 'explicit', lmap, pcpu, False, tinfo)
                    except Exception:
                        prov_m = None
                    mapping_plan.append({
                        'mapping_profile': 'explicit',
                        'mapping_variant': 'explicit',
                        'mapping_id': topo_mod.mapping_case_id_component('explicit', 'explicit', lmap),
                        'logical_node_count': logical_count,
                        'logical_to_physical': list(lmap),
                        'phys_nodes': ','.join(str(x) for x in lmap),
                        'supported': True,
                        'reason': None,
                        'topology_info': tinfo,
                        'mapping_provenance': prov_m,
                        'applies_to_scenarios': [s['id'] for s in selected],
                    })
elif req_profiles_base == ['auto'] or req_profiles_base == ['default']:
    mapping_mode = 'auto'
    if topo_discovery_err and host_usable_count == 0:
        errors.append('topology validation failed: %s' % topo_discovery_err)
    else:
        # one concrete mapping per scenario node-count using legacy auto selection
        by_count = {}
        for s in selected:
            n = s['nodes']
            if n is None:
                continue
            if n not in by_count:
                try:
                    lmap, pcpu, tinfo, terr = run_dist.resolve_topology(n, None, no_pin=False)
                except Exception as e:
                    lmap, pcpu, tinfo, terr = [], [], {}, ['resolve_topology exception: %s' % e]
                if terr or not lmap:
                    for te in (terr or ['auto mapping could not be established']):
                        errors.append('scenario %s requires %d node(s): %s' % (s['id'], n, te))
                    by_count[n] = None
                else:
                    prov = None
                    try:
                        invx = run_dist.discover_topology_inventory()
                        prov = topo_mod.build_mapping_provenance(invx or {}, 'auto', 'auto', lmap, pcpu, False, tinfo)
                    except Exception:
                        prov = None
                    by_count[n] = {
                        'mapping_profile': 'auto',
                        'mapping_variant': 'auto',
                        'mapping_id': topo_mod.mapping_case_id_component('auto', 'auto', lmap),
                        'logical_node_count': n,
                        'logical_to_physical': list(lmap),
                        'phys_nodes': ','.join(str(x) for x in lmap),
                        'supported': True,
                        'reason': None,
                        'topology_info': tinfo,
                        'mapping_provenance': prov,
                    }
        for s in selected:
            n = s['nodes']
            if n is None or by_count.get(n) is None:
                continue
            m = dict(by_count[n])
            m['applies_to_scenarios'] = [s['id']]
            # store per-scenario mapping entries (same concrete mapping may appear per scenario)
            mapping_plan.append({**m, 'scenario_id': s['id']})
else:
    mapping_mode = 'profiles'
    if topo_discovery_err and host_usable_count == 0 and inv is None:
        errors.append('topology validation failed: %s' % topo_discovery_err)
    else:
        # expand requested profiles per distinct scenario node count
        for n in selected_counts:
            try:
                variants, invx, terrs = run_dist.resolve_mapping_plan(n, profiles=req_profiles_base, phys_nodes_spec=None, no_pin=False)
            except Exception as e:
                variants, invx, terrs = [], inv, ['mapping plan failed for %d nodes: %s' % (n, e)]
            if terrs:
                errors.extend(['%d-node mapping plan: %s' % (n, te) for te in terrs])
            scen_ids_n = [s['id'] for s in selected if s['nodes'] == n]
            for v in variants:
                entry = {
                    'mapping_profile': v.get('profile'),
                    'mapping_variant': v.get('variant'),
                    'logical_node_count': n,
                    'logical_to_physical': v.get('logical_to_physical') or [],
                    'supported': bool(v.get('supported')),
                    'reason': v.get('reason'),
                    'topology_info': v.get('topology_info'),
                    'mapping_provenance': v.get('mapping_provenance'),
                    'applies_to_scenarios': scen_ids_n,
                }
                if v.get('supported') and v.get('logical_to_physical'):
                    entry['phys_nodes'] = ','.join(str(x) for x in v['logical_to_physical'])
                    entry['mapping_id'] = topo_mod.mapping_case_id_component(v.get('profile'), v.get('variant'), v['logical_to_physical'])
                else:
                    entry['mapping_id'] = '%s:unsupported' % (v.get('variant') or v.get('profile') or 'mapping')
                if entry['supported']:
                    mapping_plan.append(entry)
                else:
                    unsupported_mappings.append(entry)
        # in strict requested mode (not matrix), unsupported requested profiles are errors
        if not matrix_mode and unsupported_mappings:
            for um in unsupported_mappings:
                errors.append('requested mapping unsupported for %d-node scenarios %s: %s (%s)' % (
                    um.get('logical_node_count'), um.get('applies_to_scenarios'), um.get('mapping_variant'), um.get('reason')))

# Build case plan entries: (scenario, mapping, candidate) for supported mappings
plan_cases = []
if not errors:
    # normalize: ensure each mapping_plan entry has scenario association; for profile mode it's per node-count
    expanded = []
    for m in mapping_plan:
        if 'scenario_id' in m:
            expanded.append(m)
        else:
            for sid in m.get('applies_to_scenarios') or []:
                mm = dict(m)
                mm['scenario_id'] = sid
                expanded.append(mm)
    for m in expanded:
        plan_cases.append(m)

# Preflight must validate every mapping in complete selected plan before timed trials.
# (all entries in plan_cases are already resolved/validated above)

if errors:
    for e in errors:
        print('dist-campaign: scenario/topology validation failed before timed trials: ' + e, file=sys.stderr)
    # still write a prevalidation record for diagnostics
    prov = {
        'status': 'failed',
        'errors': errors,
        'scenario_profile_requested': requested_profile,
        'scenario_profile_effective': effective_profile,
        'scenario_profile_overridden': bool(profile_overridden),
        'scenario_profile': effective_profile,
        'profile_quick': bool(quick),
        'host_usable_nodes': host_usable_node_ids,
        'host_usable_node_count': host_usable_count,
        'selected_scenario_logical_node_counts': selected_counts,
        'selected_scenarios': [{'id': s['id'], 'nodes': s['nodes']} for s in selected],
        'scenarios_filter': scenarios_filter_record,
        'scenarios_filter_explicit': bool(scen_filter_explicit),
        'mapping_profiles_requested': raw_mp,
        'mapping_mode': ('explicit' if phys_nodes else ('matrix' if matrix_mode else 'profiles' if req_profiles_base not in (['auto'], ['default']) else 'auto')),
        'unsupported_mappings': unsupported_mappings,
    }
    os.makedirs(out, exist_ok=True)
    with open(preval_path, 'w') as f:
        json.dump(prov, f, indent=2, sort_keys=True)
    sys.exit(2)

def _safe_id(s):
    return re.sub(r'[^A-Za-z0-9_.:-]+', '-', str(s))

_eff_map_mode = ('explicit' if phys_nodes else ('matrix' if matrix_mode else 'profiles' if req_profiles_base not in (['auto'], ['default']) else 'auto'))
_eff_explicit_ids = None
_eff_explicit_count = None
_eff_resolved_explicit = None
_eff_explicit_validated = False
if phys_nodes and plan_cases:
    _eff_resolved_explicit = list(plan_cases[0].get('logical_to_physical') or [])
    _eff_explicit_ids = _eff_resolved_explicit
    _eff_explicit_count = len(_eff_resolved_explicit)
    _eff_explicit_validated = bool(explicit_mapping_validated and _eff_resolved_explicit)
elif explicit_mapping_validated and resolved_explicit_mapping is not None:
    _eff_resolved_explicit = list(resolved_explicit_mapping)
    _eff_explicit_ids = _eff_resolved_explicit
    _eff_explicit_count = len(_eff_resolved_explicit)
    _eff_explicit_validated = True

prov = {
    'status': 'ok',
    'scenario_profile_requested': requested_profile,
    'scenario_profile_effective': effective_profile,
    'scenario_profile_overridden': bool(profile_overridden),
    'scenario_profile': effective_profile,
    'profile_quick': bool(quick),
    'host_usable_nodes': host_usable_node_ids,
    'host_usable_node_count': host_usable_count,
    'available_usable_nodes': host_usable_count,
    'explicit_physical_node_ids': _eff_explicit_ids,
    'explicit_selected_node_count': _eff_explicit_count,
    'selected_scenario_logical_node_counts': selected_counts,
    'physical_node_mapping': {
        'mode': _eff_map_mode,
        'profiles_requested': raw_mp,
        'phys_nodes': _eff_explicit_ids,
        'explicit_mapping_validated': bool(_eff_explicit_validated),
        'resolved_logical_to_physical': _eff_resolved_explicit,
        'note': ('explicit mapping validated via run_dist.resolve_topology() with the same mapping/pinning semantics as trials; explicit mapping requires each selected scenario logical node count to equal the explicit selection count.'
                 if _eff_map_mode == 'explicit' else
                 'Each case carries a concrete resolved logical_to_physical mapping passed to every trial. Unsupported requested mappings are reported explicitly.'),
    },
    'mapping_plan_cases': [{
        'scenario': c['scenario_id'], 'mapping_profile': c.get('mapping_profile'),
        'mapping_variant': c.get('mapping_variant'), 'mapping_id': c.get('mapping_id'),
        'logical_node_count': c.get('logical_node_count'), 'logical_to_physical': c.get('logical_to_physical'),
        'supported': c.get('supported'), 'reason': c.get('reason'),
        'spans_sockets': (c.get('mapping_provenance') or {}).get('spans_sockets'),
    } for c in plan_cases],
    'unsupported_mappings': [{
        'mapping_profile': u.get('mapping_profile'), 'mapping_variant': u.get('mapping_variant'),
        'mapping_id': u.get('mapping_id'), 'logical_node_count': u.get('logical_node_count'),
        'applies_to_scenarios': u.get('applies_to_scenarios'), 'reason': u.get('reason'),
    } for u in unsupported_mappings],
    'selected_scenarios': [{'id': s['id'], 'nodes': s['nodes']} for s in selected],
    'scenarios_filter': scenarios_filter_record,
    'scenarios_filter_explicit': bool(scen_filter_explicit),
}
os.makedirs(out, exist_ok=True)
with open(preval_path, 'w') as f:
    json.dump(prov, f, indent=2, sort_keys=True)

# Emit execution plan for bash: scenario_id \t scen_def \t trial \t cand_csv \t mapping_id \t mapping_profile \t mapping_variant \t phys_nodes
# Also write structured plan. Use the actual validated CLI/shell values so
# plan-only and real execution agree exactly.
exec_plan = []
cand_list = list(plan_candidates)
trials_n = int(plan_trials_n)
seed = str(plan_seed)
shuf_sc = bool(plan_shuffle_scenarios)
import random
# group by (scenario,mapping) preserving scenario order
sm_keys = []
sm_map = {}
for c in plan_cases:
    key = (c['scenario_id'], c['mapping_id'])
    if key not in sm_map:
        sm_map[key] = c
        sm_keys.append(key)
scen_order = [s['id'] for s in selected]
# stable order by scenario then mapping
def sm_sort_key(k):
    try:
        si = scen_order.index(k[0])
    except ValueError:
        si = 9999
    return (si, k[1])
sm_keys = sorted(sm_keys, key=sm_sort_key)
if shuf_sc:
    random.Random(str(seed) + '|scenario_mapping_blocks').shuffle(sm_keys)

for key in sm_keys:
    m = sm_map[key]
    sid = m['scenario_id']
    for t in range(1, trials_n + 1):
        cands = list(cand_list)
        random.Random(str(seed)+'|'+sid+'|'+m['mapping_id']+'|'+str(t)).shuffle(cands)
        exec_plan.append({
            'scenario': sid,
            'scenario_def': available_by_id[sid]['def'],
            'trial': t,
            'candidate_order': cands,
            'mapping_id': m['mapping_id'],
            'mapping_profile': m.get('mapping_profile'),
            'mapping_variant': m.get('mapping_variant'),
            'logical_to_physical': m.get('logical_to_physical'),
            'phys_nodes': m.get('phys_nodes'),
        })

# Record requested/executed plan parameters in prevalidation for provenance and tests.
prov['candidates_requested'] = list(plan_candidates)
prov['candidates'] = list(plan_candidates)
prov['trials'] = trials_n
prov['seed'] = seed
prov['shuffle_scenarios'] = bool(shuf_sc)
prov['randomization'] = {
    'seed': seed,
    'shuffle_scenarios': bool(shuf_sc),
    'trials': trials_n,
    'candidates': list(plan_candidates),
}
with open(preval_path, 'w') as f:
    json.dump(prov, f, indent=2, sort_keys=True)

with open(os.path.join(out, 'execution-plan.json'), 'w') as f:
    json.dump({'seed': seed, 'shuffle_scenarios': shuf_sc, 'trials': trials_n,
               'candidates': list(plan_candidates),
               'mapping_profiles_requested': raw_mp, 'mapping_mode': prov['physical_node_mapping']['mode'],
               'blocks': exec_plan, 'unsupported_mappings': prov['unsupported_mappings']}, f, indent=2, sort_keys=True)
with open(os.path.join(out, '.run_plan.tsv'), 'w') as f:
    for b in exec_plan:
        f.write('\t'.join([
            b['scenario'], b['scenario_def'], str(b['trial']), ','.join(b['candidate_order']),
            b['mapping_id'] or '', b.get('mapping_profile') or '', b.get('mapping_variant') or '', b.get('phys_nodes') or ''
        ]) + '\n')
print('prevalidation ok: selected=%s mappings=%d unsupported=%d candidates=%s trials=%d seed=%s shuffle=%s' % (
    selected_ids, len(plan_cases), len(unsupported_mappings), plan_candidates, trials_n, seed, shuf_sc), file=sys.stderr)
PY
PREVAL_RC=$?
if [ "$PREVAL_RC" -ne 0 ]; then
  exit "$PREVAL_RC"
fi

# plan-only mode: complete plan written, no builds/corpora/timed trials
if [ "$PLAN_ONLY" -eq 1 ]; then
  echo "dist-campaign plan-only complete: $OUT" >&2
  echo "  prevalidation: $OUT/prevalidation.json" >&2
  echo "  execution-plan: $OUT/execution-plan.json" >&2
  exit 0
fi

export FORKRUN_DIAG_QUEUE=1
export DIST_TRIALS="$TRIALS"
export DIST_SEED="$SEED"
export DIST_SHUFFLE_SCENARIOS="$SHUFFLE_SCENARIOS"
export DIST_CAND_FILTER="$CAND_FILTER"

echo "=== dist-ingest campaign: build"
make -f Makefile.substrate python-substrate >/dev/null 2>&1 || echo "WARN: python-substrate build issue (continuing)"
(cd stage0/dist_ingest && make) || { echo "dist-campaign: dist_ingest build failed" >&2; exit 1; }

echo "=== dist-ingest campaign: environment"
python3 stage0/env_capture.py --out "$OUT/env/env-before.json" --run-id "$CAMPAIGN_ID" \
  || { echo "dist-campaign: env-before failed" >&2; exit 1; }

echo "=== dist-ingest campaign: corpora"
python3 - "$OUT" "$QUICK" <<'PY'
import os, sys
out, quick = sys.argv[1], sys.argv[2] == '1'
os.makedirs(os.path.join(out,'corpora'), exist_ok=True)
def make(path, size):
    if os.path.exists(path): return
    with open(path,'wb') as f:
        chunk = b'abcdefghij' * 102400
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

FAILURES=()
OUTCOMES="$OUT/.outcomes.tsv"
ORDER_LOG="$OUT/execution-order.jsonl"
: > "$OUTCOMES"
: > "$ORDER_LOG"

PLAN_FILE="$OUT/.run_plan.tsv"
while IFS=$'\t' read -r sid scen_def t cand_csv map_id map_profile map_variant map_phys; do
  [ -z "$sid" ] && continue
  IFS='|' read -r _sid inp nodes cmode cbps snode smode sbps sstall mbacklog extra <<< "$scen_def"
  IFS=',' read -ra BLOCK_CANDS <<< "$cand_csv"
  echo "BLOCK scenario=$sid mapping=$map_id trial=$t order=$cand_csv" >&2
  printf '{"scenario":"%s","mapping_id":"%s","mapping_profile":"%s","trial":%s,"candidate_order":[%s]}\n' \
    "$sid" "$map_id" "$map_profile" "$t" "$(python3 - <<PY "$cand_csv"
import json,sys; print(','.join(json.dumps(x) for x in sys.argv[1].split(',') if x))
PY
)" >> "$ORDER_LOG"
  for cand in "${BLOCK_CANDS[@]}"; do
    [ -z "$cand" ] && continue
    # mapping identity in case identity (checkpoint 1)
    safe_map=$(python3 -c "import re,sys; print(re.sub(r'[^A-Za-z0-9_.:-]+','-',sys.argv[1]))" "$map_id")
    case_id="${sid}__${safe_map}__${cand}"
    outdir="$OUT/cases/$case_id/trial$t"
    if [ -e "$outdir/manifest.json" ]; then
      echo "SKIP existing evidence: $case_id trial$t" >&2
      prev=skipped_existing
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$case_id" "$sid" "$cand" "$t" "$prev" "cases/$case_id/trial$t/manifest.json" "$map_id" "$map_profile" >> "$OUTCOMES"
      continue
    fi
    mkdir -p "$outdir" || exit 1
    spec="$outdir/spec.json"
    input_path="$OUT/$inp"
    python3 - "$spec" "$sid" "$cand" "$case_id" "$input_path" "$nodes" "$cmode" "$cbps" "$snode" "$smode" "$sbps" "$sstall" "$mbacklog" "$SEED" "$CONSUMER_KERNEL" "$STRICT_AFFINITY" "$STRICT_MBIND" "$map_phys" "$map_id" "$map_profile" "$map_variant" <<'PY'
import json, sys
(spec,sid,cand,cid,inp,nodes,cmode,cbps,snode,smode,sbps,sstall,mbacklog,seed,consumer_kernel,strict_affinity,strict_mbind,map_phys,map_id,map_profile,map_variant)=sys.argv[1:22]
d={
  "id": cid,
  "scenario": sid,
  "mapping_id": map_id or None,
  "mapping_profile": map_profile or None,
  "mapping_variant": map_variant or None,
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
    "consumer_kernel": consumer_kernel,
    "strict_affinity": bool(int(strict_affinity)),
    "strict_mbind": bool(int(strict_mbind)),
  })
  # Same resolved mapping passed to every trial in that case
  if map_phys:
    d["phys_nodes"] = map_phys
with open(spec,'w') as f: json.dump(d,f,indent=2,sort_keys=True)
PY
    if python3 stage0/run_case.py --spec "$spec" --out "$outdir" \
         --campaign-id "$CAMPAIGN_ID" --trial "$t" --source-sha "$SOURCE_SHA"; then
      status=ok
    else
      status=failed
      FAILURES+=("$case_id trial$t")
      echo "TRIAL FAILED: $case_id trial$t" >&2
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$case_id" "$sid" "$cand" "$t" "$status" "cases/$case_id/trial$t/manifest.json" "$map_id" "$map_profile" >> "$OUTCOMES"
  done
done < "$PLAN_FILE"

python3 stage0/env_capture.py --out "$OUT/env/env-after.json" --run-id "$CAMPAIGN_ID" \
  || echo "WARN: env-after capture failed" >&2

python3 - "$OUT" "$CAMPAIGN_ID" "$SOURCE_SHA" "$TRIALS" "$OUTCOMES" "$SEED" "$CACHE_POLICY" "$SHUFFLE_SCENARIOS" "$CONSUMER_KERNEL" "$STRICT_AFFINITY" "$STRICT_MBIND" "$PHYS_NODES" "$MAPPING_PROFILES" <<'PY'
import json, os, sys, time
out,cid,sha,trials,outcomes,seed,cache_policy,shuf_sc,consumer_kernel,strict_affinity,strict_mbind,phys_nodes,mapping_profiles=sys.argv[1:14]
rows=[]
with open(outcomes) as f:
    for line in f:
        line=line.rstrip('\n')
        if not line: continue
        parts = line.split('\t')
        # new format: case,scenario,candidate,trial,status,manifest,mapping_id,mapping_profile
        if len(parts) >= 8:
            case,scen,cand,t,status,man,map_id,map_prof = parts[:8]
        else:
            case,scen,cand,t,status,man = parts[:6]
            map_id = None; map_prof = None
        rows.append({"case":case,"scenario":scen,"candidate":cand,"trial":int(t),"status":status,
                     "manifest":man,"mapping_id":map_id,"mapping_profile":map_prof})
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
preval=None
ppath=os.path.join(out,'prevalidation.json')
if os.path.isfile(ppath):
    with open(ppath) as f: preval=json.load(f)
all_ok = all(r['status'] in ('ok','skipped_existing') for r in rows) if rows else False
doc={"schema":"dist-campaign/5","campaign_id":cid,"source_sha":sha,"trials":int(trials),
     "randomization":{"seed":seed,"shuffle_scenarios":(shuf_sc=='1'),"execution_order":order,"plan":plan},
     "cache_policy":cache_policy,
     "campaign_config":{
        "consumer_kernel": consumer_kernel,
        "strict_affinity": strict_affinity=='1',
        "strict_mbind": strict_mbind=='1',
        "phys_nodes": phys_nodes or None,
        "mapping_profiles": mapping_profiles,
        "notes": "strict flags/kernel applied identically per comparable dist-engine candidate spec; strict mode must not silently fall back"
     },
     "scenario_profile": (preval or {}).get('scenario_profile'),
     "scenario_profile_requested": (preval or {}).get('scenario_profile_requested'),
     "scenario_profile_effective": (preval or {}).get('scenario_profile_effective'),
     "scenario_profile_overridden": (preval or {}).get('scenario_profile_overridden'),
     "host_usable_nodes": (preval or {}).get('host_usable_nodes'),
     "host_usable_node_count": (preval or {}).get('host_usable_node_count'),
     "available_usable_nodes": (preval or {}).get('available_usable_nodes'),
     "explicit_physical_node_ids": (preval or {}).get('explicit_physical_node_ids'),
     "explicit_selected_node_count": (preval or {}).get('explicit_selected_node_count'),
     "selected_scenario_logical_node_counts": (preval or {}).get('selected_scenario_logical_node_counts'),
     "selected_scenarios": (preval or {}).get('selected_scenarios'),
     "physical_node_mapping": (preval or {}).get('physical_node_mapping'),
     "mapping_plan_cases": (preval or {}).get('mapping_plan_cases'),
     "unsupported_mappings": (preval or {}).get('unsupported_mappings'),
     "scenarios_filter_explicit": (preval or {}).get('scenarios_filter_explicit'),
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
