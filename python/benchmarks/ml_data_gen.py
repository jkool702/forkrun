"""Synthetic recommendation-system-style event data generator (W-PY24).

Simulates user interaction events with heterogeneous
categorical/numerical/nested JSON records.

Distributions are synthetic assumptions chosen to create realistic
data shapes — they are not empirical production distributions.

Deterministic (seeded) for reproducible benchmarks.
"""

import json
import random

SEED = 42

EVENT_TYPES = ["view", "click", "scroll", "hover", "purchase", "skip"]
EVENT_WEIGHTS = [40, 25, 15, 10, 5, 5]
DEVICES = ["ios", "android", "web", "desktop", "tablet"]
DEVICE_WEIGHTS = [30, 35, 20, 10, 5]
TIERS = ["free", "basic", "premium"]
TIER_WEIGHTS = [60, 30, 10]


def generate_event(rng, variant="medium"):
    """Generate one synthetic event.

    variant controls record complexity:
    - "light": flat JSON, few fields (parse-dominated)
    - "medium": nested JSON, moderate fields (standard data prep)
    - "heavy": nested JSON + text content (expensive UDF)
    """
    event_type = rng.choices(EVENT_TYPES, weights=EVENT_WEIGHTS)[0]
    device = rng.choices(DEVICES, weights=DEVICE_WEIGHTS)[0]
    tier = rng.choices(TIERS, weights=TIER_WEIGHTS)[0]

    if variant == "light":
        return {
            "eid": "evt_%012x" % rng.getrandbits(48),
            "uid": rng.randint(1, 1_000_000),
            "iid": rng.randint(1, 50_000),
            "ts": 1700000000 + rng.randint(0, 86400 * 365),
            "et": event_type,
            "dev": device,
            "dur": rng.randint(50, 120_000),
        }

    if variant == "medium":
        return {
            "event_id": "evt_%012x" % rng.getrandbits(48),
            "user_id": "user_%08d" % rng.randint(1, 1_000_000),
            "item_id": "item_%06d" % rng.randint(1, 50_000),
            "session_id": "sess_%012x" % rng.getrandbits(48),
            "timestamp": 1700000000 + rng.randint(0, 86400 * 365),
            "event_type": event_type,
            "device": device,
            "duration_ms": rng.randint(50, 120_000),
            "scroll_depth": round(rng.uniform(0.0, 1.0), 3),
            "revenue_cents": (rng.randint(100, 9999)
                              if event_type == "purchase" else 0),
            "user_context": {
                "num_prev_sessions": rng.randint(1, 500),
                "avg_session_duration_s": round(rng.uniform(30, 3600), 1),
                "user_tier": tier,
                "days_since_signup": rng.randint(1, 3650),
            },
            "item_context": {
                "category": "cat_%03d" % rng.randint(1, 200),
                "price_cents": rng.randint(99, 99_999),
                "rating": round(rng.uniform(1.0, 5.0), 1),
                "num_reviews": rng.randint(0, 10_000),
            },
            "experiment_bucket": "exp_%s" % rng.choice("ABCDE"),
        }

    if variant == "heavy":
        # Medium + text fields for the expensive Python UDF.
        event = generate_event(rng, "medium")
        words = ["the", "quick", "brown", "fox", "jumps", "over",
                 "lazy", "dog", "product", "quality", "excellent",
                 "recommend", "purchase", "value", "shipping", "fast",
                 "service", "great", "good", "bad"]
        n_words = rng.randint(50, 200)
        event["review_text"] = " ".join(
            rng.choice(words) for _ in range(n_words))
        event["search_query"] = " ".join(
            rng.choice(words) for _ in range(rng.randint(3, 10)))
        return event

    raise ValueError("unknown variant %r" % (variant,))


def generate_data(path, n_records, variant="medium", malformed_pct=0.0):
    """Generate synthetic JSONL data (deterministic, seeded).

    malformed_pct: percentage of malformed records (0-100).
    Returns path.
    """
    rng = random.Random(SEED)

    with open(path, "w") as fh:
        for _ in range(n_records):
            if rng.random() * 100 < malformed_pct:
                malform = rng.choice(["truncated", "missing_field",
                                      "wrong_type", "garbage", "empty"])
                if malform == "truncated":
                    event = generate_event(rng, variant)
                    line = json.dumps(event, separators=(",", ":"))
                    cut = rng.randint(10, max(11, len(line) - 1))
                    fh.write(line[:cut] + "\n")
                elif malform == "missing_field":
                    event = generate_event(rng, variant)
                    del event[rng.choice(list(event.keys()))]
                    fh.write(json.dumps(event, separators=(",", ":"))
                             + "\n")
                elif malform == "wrong_type":
                    event = generate_event(rng, variant)
                    event["timestamp"] = "not_a_number"
                    fh.write(json.dumps(event, separators=(",", ":"))
                             + "\n")
                elif malform == "garbage":
                    fh.write("{%s\n" % ("x" * rng.randint(20, 200)))
                elif malform == "empty":
                    fh.write("\n")
            else:
                event = generate_event(rng, variant)
                fh.write(json.dumps(event, separators=(",", ":")) + "\n")

    return path
