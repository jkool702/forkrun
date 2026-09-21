"""Native-expression implementations for Polars and DuckDB (W-PY24).

SEPARATE from the UDF benchmark. Answers: "how fast is the workload
when rewritten in the native execution model?"

Polars uses lazy/streaming NDJSON with native expressions. DuckDB
uses SQL with JSON functions. Both get the same logical workload
but use their own optimization machinery (columnar execution,
vectorization). Only the medium variant is expressed natively —
the heavy variant's arbitrary Python UDF (tokenize/stem/hash) is
precisely what native engines cannot express, which is the point.
"""

EVENT_MAP = {"view": 0, "click": 1, "scroll": 2, "hover": 3,
             "purchase": 4, "skip": 5}
DEVICE_MAP = {"ios": 0, "android": 1, "web": 2, "desktop": 3, "tablet": 4}
TIER_MAP = {"free": 0, "basic": 1, "premium": 2}
BASE_TS = 1700000000


def polars_medium(input_path, output_path=None):
    """Medium workload with Polars native expressions."""
    import polars as pl

    df = pl.scan_ndjson(input_path)

    result = (
        df
        .filter(
            (pl.col("duration_ms") >= 100)
            & (pl.col("event_type").is_in(list(EVENT_MAP.keys())))
        )
        .with_columns([
            ((pl.col("timestamp") - BASE_TS) / 86400.0).alias("ts_n"),
            ((pl.col("timestamp") % 86400) // 3600).alias("hod"),
            ((pl.col("timestamp") // 86400) % 7).alias("dow"),
            pl.col("event_type").replace_strict(
                EVENT_MAP, default=-1).alias("et"),
            pl.col("device").replace_strict(
                DEVICE_MAP, default=-1).alias("dev"),
            pl.col("duration_ms").log1p().round(4).alias("log_dur"),
            pl.col("scroll_depth").fill_null(0.0).alias("scr"),
            (pl.col("revenue_cents").fill_null(0) > 0)
            .cast(pl.Int32).alias("rev"),
            pl.col("user_context").struct.field("user_tier")
            .replace_strict(TIER_MAP, default=0).alias("tier"),
            pl.col("user_context").struct.field(
                "num_prev_sessions").fill_null(0).alias("sess"),
            pl.col("user_context").struct.field(
                "days_since_signup").fill_null(0).alias("dss"),
            pl.col("item_context").struct.field(
                "price_cents").fill_null(0).log1p().round(4)
            .alias("log_pr"),
            pl.col("item_context").struct.field("rating")
            .fill_null(0.0).alias("rate"),
        ])
        .select([
            "event_id", "user_id", "item_id",
            "ts_n", "hod", "dow", "et", "dev",
            "log_dur", "scr", "rev", "tier", "sess", "dss",
            "log_pr", "rate",
        ])
    )

    if output_path:
        result.sink_parquet(output_path)
        return None
    return result.collect()


def duckdb_medium(input_path, output_path=None):
    """Medium workload with DuckDB SQL over NDJSON."""
    import duckdb

    con = duckdb.connect()
    query = (
        "SELECT "
        "event_id, user_id, item_id, "
        "(timestamp - %d) / 86400.0 AS ts_n, "
        "(timestamp %% 86400) / 3600 AS hod, "
        "(timestamp / 86400) %% 7 AS dow, "
        "CASE event_type "
        "WHEN 'view' THEN 0 WHEN 'click' THEN 1 "
        "WHEN 'scroll' THEN 2 WHEN 'hover' THEN 3 "
        "WHEN 'purchase' THEN 4 WHEN 'skip' THEN 5 "
        "ELSE -1 END AS et, "
        "CASE device "
        "WHEN 'ios' THEN 0 WHEN 'android' THEN 1 "
        "WHEN 'web' THEN 2 WHEN 'desktop' THEN 3 "
        "WHEN 'tablet' THEN 4 ELSE -1 END AS dev, "
        "ROUND(ln(duration_ms + 1), 4) AS log_dur, "
        "COALESCE(scroll_depth, 0.0) AS scr, "
        "CASE WHEN COALESCE(revenue_cents, 0) > 0 THEN 1 ELSE 0 END "
        "AS rev, "
        "CASE user_context.user_tier "
        "WHEN 'free' THEN 0 WHEN 'basic' THEN 1 "
        "WHEN 'premium' THEN 2 ELSE 0 END AS tier, "
        "COALESCE(user_context.num_prev_sessions, 0) AS sess, "
        "COALESCE(user_context.days_since_signup, 0) AS dss, "
        "ROUND(ln(COALESCE(item_context.price_cents, 0) + 1), 4) "
        "AS log_pr, "
        "COALESCE(item_context.rating, 0.0) AS rate "
        "FROM read_json_auto('%s') "
        "WHERE duration_ms >= 100 "
        "AND event_type IN ('view', 'click', 'scroll', 'hover', "
        "'purchase', 'skip')" % (BASE_TS, input_path)
    )

    if output_path:
        con.execute("COPY (%s) TO '%s' (FORMAT PARQUET)"
                    % (query, output_path))
        con.close()
        return None
    result = con.execute(query).fetchall()
    con.close()
    return result
