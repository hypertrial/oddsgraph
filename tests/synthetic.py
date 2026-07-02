from __future__ import annotations

from pathlib import Path
from typing import Any

from oddsgraph import thresholds as T
from oddsgraph.queries import DuckDB, q
from oddsgraph.sql import values_rows_sql


MARKET_COLUMNS = [
    "market_id",
    "question",
    "event_slug",
    "yes_base",
    "yes_current",
    "no_base",
    "no_current",
    "volume",
    "minute_count",
    "start_epoch",
]


def _values(rows: list[tuple[Any, ...]], columns: list[str]) -> str:
    return values_rows_sql([dict(zip(columns, row, strict=True)) for row in rows], columns)


def write_synthetic_input(path: Path) -> None:
    markets = [
        ("comp", "Will Complement pass?", "comp-event", 0.42, 0.42, 0.58, 0.58, 20_000.0, 1000, 0),
        ("bad", "Will Bad Sum pass?", "bad-event", 0.70, 0.70, 0.70, 0.70, 20_000.0, 1000, 10_000),
        ("eq_a", "Will Equivalent A happen?", "eq-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 20_000),
        ("eq_b", "Will Equivalent B happen?", "eq-event", 0.56, 0.56, 0.44, 0.44, 20_000.0, 1000, 20_000),
        ("eq_shift_a", "Will Shift A happen?", "eq-shift-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 30_000),
        ("eq_shift_b", "Will Shift B happen?", "eq-shift-event", 0.60, 0.60, 0.40, 0.40, 20_000.0, 1000, 30_000),
        ("eq_spike_a", "Will Spike A happen?", "eq-spike-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 40_000),
        ("eq_spike_b", "Will Spike B happen?", "eq-spike-event", 0.56, 0.70, 0.44, 0.30, 20_000.0, 1000, 40_000),
        ("imp_a", "Will Specific outcome happen?", "imp-event", 0.70, 0.70, 0.30, 0.30, 20_000.0, 1000, 50_000),
        ("imp_b", "Will Broader outcome happen?", "imp-event", 0.90, 0.90, 0.10, 0.10, 20_000.0, 1000, 50_000),
        ("imp_mean_bad_a", "Will Mean Bad A happen?", "imp-mean-bad-event", 0.80, 0.80, 0.20, 0.20, 20_000.0, 1000, 60_000),
        ("imp_mean_bad_b", "Will Mean Bad B happen?", "imp-mean-bad-event", 0.70, 0.70, 0.30, 0.30, 20_000.0, 1000, 60_000),
        ("imp_current_bad_a", "Will Current Bad A happen?", "imp-current-bad-event", 0.70, 0.95, 0.30, 0.05, 20_000.0, 1000, 70_000),
        ("imp_current_bad_b", "Will Current Bad B happen?", "imp-current-bad-event", 0.90, 0.90, 0.10, 0.10, 20_000.0, 1000, 70_000),
        ("excl_a", "Will Exclusion A happen?", "excl-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 80_000),
        ("excl_b", "Will Exclusion B happen?", "excl-event", 0.45, 0.45, 0.55, 0.55, 20_000.0, 1000, 80_000),
        ("excl_mean_bad_a", "Will Exclusion Mean Bad A happen?", "excl-mean-bad-event", 0.70, 0.70, 0.30, 0.30, 20_000.0, 1000, 90_000),
        ("excl_mean_bad_b", "Will Exclusion Mean Bad B happen?", "excl-mean-bad-event", 0.40, 0.40, 0.60, 0.60, 20_000.0, 1000, 90_000),
        ("excl_current_bad_a", "Will Exclusion Current Bad A happen?", "excl-current-bad-event", 0.55, 0.70, 0.45, 0.30, 20_000.0, 1000, 100_000),
        ("excl_current_bad_b", "Will Exclusion Current Bad B happen?", "excl-current-bad-event", 0.45, 0.45, 0.55, 0.55, 20_000.0, 1000, 100_000),
        ("low_volume_a", "Will Low Volume A happen?", "low-volume-event", 0.55, 0.55, 0.45, 0.45, T.MIN_MARKET_VOLUME_USD - 1, 1000, 110_000),
        ("low_volume_b", "Will Low Volume B happen?", "low-volume-event", 0.56, 0.56, 0.44, 0.44, T.MIN_MARKET_VOLUME_USD - 1, 1000, 110_000),
        ("low_active_a", "Will Low Active A happen?", "low-active-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, T.MIN_ACTIVE_MINUTES - 1, 120_000),
        ("low_active_b", "Will Low Active B happen?", "low-active-event", 0.56, 0.56, 0.44, 0.44, 20_000.0, T.MIN_ACTIVE_MINUTES - 1, 120_000),
        ("low_overlap_a", "Will Low Overlap A happen?", "low-overlap-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 130_000),
        ("low_overlap_b", "Will Low Overlap B happen?", "low-overlap-event", 0.56, 0.56, 0.44, 0.44, 20_000.0, 1000, 130_950),
        ("diff_event_a", "Will Different Event A happen?", "diff-event-a", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 140_000),
        ("diff_event_b", "Will Different Event B happen?", "diff-event-b", 0.56, 0.56, 0.44, 0.44, 20_000.0, 1000, 140_000),
        ("dup_same_a", "Will Duplicate Semantic happen?", "dup-sem-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 150_000),
        ("dup_same_b", "Will Duplicate Semantic happen?", "dup-sem-event", 0.56, 0.56, 0.44, 0.44, 20_000.0, 1000, 150_000),
        ("dup_cross_a", "Will Cross Event Duplicate happen?", "dup-cross-a", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 160_000),
        ("dup_cross_b", "Will Cross Event Duplicate happen?", "dup-cross-b", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 160_000),
        ("winner_alpha", "Will Alpha win the 2026 FIFA World Cup?", "world-cup-winner", 0.35, 0.35, 0.65, 0.65, 20_000.0, 1000, 170_000),
        ("winner_beta", "Will Beta win the 2026 FIFA World Cup?", "world-cup-winner", 0.25, 0.25, 0.75, 0.75, 20_000.0, 1000, 170_000),
        ("alpha_final", "Will Alpha reach the 2026 FIFA World Cup final?", "world-cup-nation-to-reach-final", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 180_000),
        ("alpha_semis", "Will Alpha reach the Semifinals at the 2026 FIFA World Cup?", "world-cup-nation-to-reach-semifinals", 0.75, 0.75, 0.25, 0.25, 20_000.0, 1000, 190_000),
    ]
    db = DuckDB(path.with_suffix(".duckdb"))
    try:
        db.execute(
            f"""
            CREATE TABLE fixture AS
            WITH market_defs(
                market_id,
                question,
                event_slug,
                yes_base,
                yes_current,
                no_base,
                no_current,
                volume,
                minute_count,
                start_epoch
            ) AS (
                VALUES
                {_values(markets, MARKET_COLUMNS)}
            ),
            minute AS (
                SELECT range::BIGINT AS i
                FROM range(1001)
            ),
            binary_rows AS (
                SELECT
                    market_id,
                    outcome_index,
                    market_id || ':' || outcome_label AS clob_token_id,
                    question,
                    outcome_label,
                    event_slug,
                    true AS is_active,
                    false AS is_closed,
                    volume AS market_volume_usd,
                    to_timestamp(start_epoch + i * 60) AS ODDS_TIMESTAMP,
                    (start_epoch + i * 60)::BIGINT AS ODDS_TIMESTAMP_EPOCH,
                    CASE outcome_label
                        WHEN 'Yes' THEN CASE WHEN i = minute_count - 1 THEN yes_current ELSE yes_base END
                        ELSE CASE WHEN i = minute_count - 1 THEN no_current ELSE no_base END
                    END AS price
                FROM market_defs
                JOIN minute ON i < minute_count
                CROSS JOIN (VALUES (0, 'Yes'), (1, 'No')) AS o(outcome_index, outcome_label)
            ),
            named_rows AS (
                SELECT
                    'named' AS market_id,
                    outcome_index,
                    'named:' || outcome_label AS clob_token_id,
                    'Top goalscorer?' AS question,
                    outcome_label,
                    'named-event' AS event_slug,
                    true AS is_active,
                    false AS is_closed,
                    1.0 AS market_volume_usd,
                    to_timestamp(200000 + i * 60) AS ODDS_TIMESTAMP,
                    (200000 + i * 60)::BIGINT AS ODDS_TIMESTAMP_EPOCH,
                    CASE outcome_label WHEN 'Messi' THEN 0.55 ELSE 0.45 END AS price
                FROM (SELECT * FROM minute LIMIT 3)
                CROSS JOIN (VALUES (0, 'Messi'), (1, 'Ronaldo')) AS o(outcome_index, outcome_label)
            ),
            nary_rows AS (
                SELECT
                    'golden_boot' AS market_id,
                    outcome_index,
                    'golden_boot:' || outcome_label AS clob_token_id,
                    'Who wins Golden Boot?' AS question,
                    outcome_label,
                    'world-cup-golden-boot-winner' AS event_slug,
                    true AS is_active,
                    false AS is_closed,
                    20_000.0 AS market_volume_usd,
                    to_timestamp(220000 + i * 60) AS ODDS_TIMESTAMP,
                    (220000 + i * 60)::BIGINT AS ODDS_TIMESTAMP_EPOCH,
                    CASE outcome_label
                        WHEN 'Alpha' THEN 0.34
                        WHEN 'Beta' THEN 0.33
                        ELSE 0.33
                    END AS price
                FROM minute
                CROSS JOIN (VALUES (0, 'Alpha'), (1, 'Beta'), (2, 'Gamma')) AS o(outcome_index, outcome_label)
                WHERE i < 1000
            ),
            stale_rows AS (
                SELECT 'stale', 0, 'stale:Yes', 'Will stale pass?', 'Yes', 'stale-event', true, false, 1.0,
                    to_timestamp(210000), 210000::BIGINT, 0.2
                UNION ALL SELECT 'stale', 1, 'stale:No', 'Will stale pass?', 'No', 'stale-event', true, false, 1.0,
                    to_timestamp(210000), 210000::BIGINT, 0.8
                UNION ALL SELECT 'stale', 0, 'stale:Yes', 'Will stale pass?', 'Yes', 'stale-event', true, false, 1.0,
                    to_timestamp(210061), 210061::BIGINT, 0.9
            )
            SELECT * FROM binary_rows
            UNION ALL SELECT * FROM named_rows
            UNION ALL SELECT * FROM nary_rows
            UNION ALL SELECT * FROM stale_rows;

            COPY fixture TO '{q(path)}' (FORMAT PARQUET);
            """
        )
    finally:
        db.close()


def write_synthetic_resolutions(path: Path) -> None:
    rows = [
        {"clob_token_id": "comp:Yes", "market_id": "comp", "outcome_label": "Yes", "payout": 1.0, "resolved_epoch": 300000},
        {"clob_token_id": "comp:No", "market_id": "comp", "outcome_label": "No", "payout": 0.0, "resolved_epoch": 300000},
        {"clob_token_id": "winner_alpha:Yes", "market_id": "winner_alpha", "outcome_label": "Yes", "payout": 0.0, "resolved_epoch": 300000},
        {"clob_token_id": "alpha_final:Yes", "market_id": "alpha_final", "outcome_label": "Yes", "payout": 0.0, "resolved_epoch": 300000},
    ]
    columns = ["clob_token_id", "market_id", "outcome_label", "payout", "resolved_epoch"]
    db = DuckDB(path.with_suffix(".duckdb"))
    try:
        db.execute(f"""
            COPY (
                SELECT
                    clob_token_id,
                    market_id,
                    outcome_label,
                    payout,
                    to_timestamp(resolved_epoch) AS resolved_at
                FROM (VALUES {values_rows_sql(rows, columns)})
                    AS t(clob_token_id, market_id, outcome_label, payout, resolved_epoch)
            ) TO '{q(path)}' (FORMAT PARQUET);
        """)
    finally:
        db.close()
