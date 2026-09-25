"""ML event processing payload — the Python transformation (W-PY24).

Three workload variants:
  ML-PREP-1 (light): Parse + validate
  ML-PREP-2 (medium): Parse + validate + extract + transform
  ML-PREP-3 (heavy): Parse + validate + extract + expensive Python UDF

The SAME logical function is given to all UDF competitors
(forkrun, Ray Data, Pool, ProcessPoolExecutor, HF Datasets).
Each framework optimizes batching, scheduling, transport, and
worker count; the transformation logic itself is identical.
"""

import json
import math
import re

EVENT_MAP = {"view": 0, "click": 1, "scroll": 2, "hover": 3,
             "purchase": 4, "skip": 5}
DEVICE_MAP = {"ios": 0, "android": 1, "web": 2, "desktop": 3, "tablet": 4}
TIER_MAP = {"free": 0, "basic": 1, "premium": 2}
BASE_TS = 1700000000

REQUIRED_LIGHT = {"eid", "uid", "iid", "ts", "et", "dev", "dur"}
REQUIRED_MEDIUM = {"event_id", "user_id", "item_id", "timestamp",
                   "event_type", "device"}


# --- ML-PREP-1: Parse + Validate (lightweight) ---

def process_event_light(line_bytes):
    """Parse JSON, validate required fields, return compact form."""
    try:
        record = json.loads(line_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Malformed JSON")

    if not isinstance(record, dict):
        raise ValueError("Not a dict")

    for field in REQUIRED_LIGHT:
        if field not in record:
            raise ValueError("Missing: %s" % field)

    if not isinstance(record["ts"], (int, float)):
        raise ValueError("ts not numeric")

    if record["dur"] < 50:
        return None  # Quality filter

    return json.dumps({
        "e": record["eid"],
        "u": record["uid"],
        "i": record["iid"],
        "t": record["ts"] - BASE_TS,
        "v": EVENT_MAP.get(record["et"], -1),
        "d": DEVICE_MAP.get(record["dev"], -1),
    }, separators=(",", ":")).encode()


# --- ML-PREP-2: Full Feature Extraction (standard) ---

def process_event_medium(line_bytes):
    """Parse, validate, extract features, transform, filter."""
    try:
        record = json.loads(line_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Malformed JSON")

    if not isinstance(record, dict):
        raise ValueError("Not a dict")

    for field in REQUIRED_MEDIUM:
        if field not in record:
            raise ValueError("Missing: %s" % field)

    if not isinstance(record["timestamp"], (int, float)):
        raise ValueError("timestamp not numeric")

    # Quality filter
    if record.get("duration_ms", 0) < 100:
        return None
    if record.get("event_type") not in EVENT_MAP:
        return None

    # Feature extraction
    user_ctx = record.get("user_context", {})
    item_ctx = record.get("item_context", {})

    return json.dumps({
        "eid": record["event_id"],
        "uid": record["user_id"],
        "iid": record["item_id"],
        "ts_n": (record["timestamp"] - BASE_TS) / 86400.0,
        "hod": (record["timestamp"] % 86400) // 3600,
        "dow": (record["timestamp"] // 86400) % 7,
        "et": EVENT_MAP[record["event_type"]],
        "dev": DEVICE_MAP.get(record["device"], -1),
        "log_dur": round(math.log1p(record.get("duration_ms", 0)), 4),
        "scr": record.get("scroll_depth", 0.0),
        "rev": 1 if record.get("revenue_cents", 0) > 0 else 0,
        "tier": TIER_MAP.get(user_ctx.get("user_tier", "free"), 0),
        "sess": user_ctx.get("num_prev_sessions", 0),
        "dss": user_ctx.get("days_since_signup", 0),
        "log_pr": round(math.log1p(item_ctx.get("price_cents", 0)), 4),
        "rate": item_ctx.get("rating", 0.0),
    }, separators=(",", ":")).encode()


# --- ML-PREP-3: Expensive Python UDF (compute-bound) ---

_TOKEN_RE = re.compile(r"\b[a-z]+\b")
_STEM_SUFFIXES = ["ing", "ed", "ly", "es", "s", "ment", "ness",
                  "ful", "less"]


def _simple_stem(word):
    """Simulated stemming — realistic Python string-processing cost."""
    for suffix in _STEM_SUFFIXES:
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[:-len(suffix)]
    return word


def _tokenize_and_hash(text):
    """Tokenize, stem, compute a feature hash.

    Deliberately CPU-heavy in Python — simulates the arbitrary
    Python UDF that cannot be expressed in native dataframe/SQL
    expressions.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    stemmed = [_simple_stem(t) for t in tokens]

    word_count = len(stemmed)
    unique_words = len(set(stemmed))

    feature_hash = 0
    for token in stemmed:
        feature_hash = (feature_hash * 31 + hash(token)) & 0xFFFFFFFF

    diversity = unique_words / word_count if word_count > 0 else 0.0

    return {
        "wc": word_count,
        "uw": unique_words,
        "fh": feature_hash,
        "ld": round(diversity, 4),
    }


def process_event_heavy(line_bytes):
    """Parse + validate + extract + expensive UDF (tokenization)."""
    result = process_event_medium(line_bytes)
    if result is None:
        return None

    record = json.loads(line_bytes)

    review_text = record.get("review_text", "")
    search_query = record.get("search_query", "")

    review_features = _tokenize_and_hash(review_text)
    query_features = _tokenize_and_hash(search_query)

    output = json.loads(result)
    output.update({
        "rv_wc": review_features["wc"],
        "rv_uw": review_features["uw"],
        "rv_fh": review_features["fh"],
        "rv_ld": review_features["ld"],
        "sq_wc": query_features["wc"],
        "sq_fh": query_features["fh"],
    })

    return json.dumps(output, separators=(",", ":")).encode()


# --- Batch-level wrappers (identical logic per framework) ---

def _forkrun_batch(data, fn):
    results = []
    for line in data.split(b"\n"):
        line = line.strip()
        if not line:
            continue
        try:
            r = fn(line)
            if r is not None:
                results.append(r)
        except ValueError:
            continue
    return b"\n".join(results) if results else None


def forkrun_payload_light(batch):
    """forkrun batch payload — light variant."""
    return _forkrun_batch(bytes(batch.data), process_event_light)


def forkrun_payload_medium(batch):
    """forkrun batch payload — medium variant."""
    return _forkrun_batch(bytes(batch.data), process_event_medium)


def forkrun_payload_heavy(batch):
    """forkrun batch payload — heavy variant."""
    return _forkrun_batch(bytes(batch.data), process_event_heavy)


def _pool_chunk(lines, fn):
    results = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if isinstance(line, str):
            line = line.encode()
        try:
            r = fn(line)
            if r is not None:
                results.append(r.decode() if isinstance(r, bytes)
                               else r)
        except ValueError:
            continue
    return results


def pool_chunk_payload_light(lines):
    """Pool chunk payload — light variant (same logic)."""
    return _pool_chunk(lines, process_event_light)


def pool_chunk_payload_medium(lines):
    """Pool chunk payload — medium variant (same logic)."""
    return _pool_chunk(lines, process_event_medium)


def pool_chunk_payload_heavy(lines):
    """Pool chunk payload — heavy variant (same logic)."""
    return _pool_chunk(lines, process_event_heavy)


def process_serial(lines, variant):
    """Serial baseline over decoded lines (same logic)."""
    fn = {"light": process_event_light,
          "medium": process_event_medium,
          "heavy": process_event_heavy}[variant]
    return _pool_chunk(lines, fn)
