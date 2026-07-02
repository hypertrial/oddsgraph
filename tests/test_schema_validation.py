from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from oddsgraph.queries import DuckDB, q
from oddsgraph.schema import validate_input
from oddsgraph.sql import sql_literal


BASE_ROWS = [
    ("m1", 0, "m1:Yes", "Will M1 pass?", "Yes", "event-1", True, False, 1.0, 1, 0.4),
    ("m1", 1, "m1:No", "Will M1 pass?", "No", "event-1", True, False, 1.0, 1, 0.6),
]


def test_schema_rejects_missing_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.parquet"
    db = DuckDB(tmp_path / "bad.duckdb")
    try:
        db.execute(f"COPY (SELECT 'm1' AS market_id) TO '{q(path)}' (FORMAT PARQUET)")
        with pytest.raises(ValueError, match="missing required columns"):
            validate_input(db, path)
    finally:
        db.close()

@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([("m1", 0, "m1:Yes", None, "Yes", "event-1", True, False, 1.0, 1, 0.4),
          ("m1", 1, "m1:No", "Will M1 pass?", "No", "event-1", True, False, 1.0, 1, 0.6)],
         "null required values: 1 rows"),
        ([("m1", 0, "m1:Yes", "Will M1 pass?", "Yes", "event-1", True, False, 1.0, 1, 1.2),
          ("m1", 1, "m1:No", "Will M1 pass?", "No", "event-1", True, False, 1.0, 1, 0.6)],
         "prices outside \\[0, 1\\]: 1 rows"),
        (BASE_ROWS + [BASE_ROWS[0]], "duplicate token timestamp rows: 1 groups"),
        ([*BASE_ROWS,
          ("m1", 0, "m1:Yes", "Will M1 changed pass?", "Yes", "event-1", True, False, 1.0, 2, 0.4),
          ("m1", 1, "m1:No", "Will M1 pass?", "No", "event-1", True, False, 1.0, 2, 0.6)],
         "unstable token metadata: 1 tokens"),
        ([BASE_ROWS[0]], "markets with fewer than 2 tokens: 1 markets"),
        ([("m1", 0, "m1:Yes", "Will M1 pass?", "Yes", "event-1", True, False, 1.0, 1, 0.4),
          ("m1", 1, "m1:No", "Will M1 pass?", "No", "event-1", True, False, 1.0, 61, 0.6)],
         "markets without complete current minute: 1 markets"),
    ],
)
def test_schema_rejects_invalid_invariants(tmp_path: Path, rows: list[tuple[Any, ...]], message: str) -> None:
    path = tmp_path / "bad.parquet"
    _write_input(path, rows)
    db = DuckDB(tmp_path / "bad.duckdb")
    try:
        with pytest.raises(ValueError, match=message):
            validate_input(db, path)
    finally:
        db.close()

def _write_input(path: Path, rows: list[tuple[Any, ...]]) -> None:
    db = DuckDB(path.with_suffix(".duckdb"))
    try:
        db.execute(f"""
            COPY (
                WITH rows(
                    market_id,
                    outcome_index,
                    clob_token_id,
                    question,
                    outcome_label,
                    event_slug,
                    is_active,
                    is_closed,
                    market_volume_usd,
                    odds_epoch,
                    price
                ) AS (
                    VALUES {_values(rows)}
                )
                SELECT
                    market_id,
                    outcome_index,
                    clob_token_id,
                    question,
                    outcome_label,
                    event_slug,
                    is_active,
                    is_closed,
                    market_volume_usd,
                    to_timestamp(odds_epoch) AS ODDS_TIMESTAMP,
                    odds_epoch::BIGINT AS ODDS_TIMESTAMP_EPOCH,
                    price
                FROM rows
            ) TO '{q(path)}' (FORMAT PARQUET)
        """)
    finally:
        db.close()

def _values(rows: list[tuple[Any, ...]]) -> str:
    return ", ".join("(" + ", ".join(sql_literal(value) for value in row) + ")" for row in rows)
