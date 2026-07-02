from __future__ import annotations

from pathlib import Path

import pytest

from oddsgraph.build import (
    _create_token_minute_prices,
    _validate_final_edge_invariants,
    _validate_token_minute_prices,
)
from oddsgraph.contracts import validate_relation_columns
from oddsgraph.queries import DuckDB


def test_token_minute_prices_choose_latest_timestamp_per_minute(tmp_path: Path) -> None:
    db = DuckDB(tmp_path / "dedupe.duckdb")
    try:
        db.execute("""
            CREATE TABLE input_prices AS
            SELECT *
            FROM (VALUES
                ('m1', 0, 'a', 'Question A', 'Yes', 'event-1', true, false, 1.0, to_timestamp(1), 1::BIGINT, 0::BIGINT, 0.40),
                ('m1', 0, 'a', 'Question A', 'Yes', 'event-1', true, false, 1.0, to_timestamp(45), 45::BIGINT, 0::BIGINT, 0.45),
                ('m1', 0, 'a', 'Question A', 'Yes', 'event-1', true, false, 1.0, to_timestamp(75), 75::BIGINT, 60::BIGINT, 0.50),
                ('m1', 1, 'b', 'Question A', 'No', 'event-1', true, false, 1.0, to_timestamp(2), 2::BIGINT, 0::BIGINT, 0.60),
                ('m1', 1, 'b', 'Question A', 'No', 'event-1', true, false, 1.0, to_timestamp(55), 55::BIGINT, 0::BIGINT, 0.55)
            ) AS t(
                market_id,
                outcome_index,
                clob_token_id,
                question,
                outcome_label,
                event_slug,
                is_active,
                is_closed,
                market_volume_usd,
                odds_timestamp,
                odds_timestamp_epoch,
                odds_minute_epoch,
                price
            );

            CREATE TABLE token_minute_reference AS
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
                odds_timestamp,
                odds_timestamp_epoch,
                odds_minute_epoch,
                price
            FROM (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY clob_token_id, odds_minute_epoch
                        ORDER BY odds_timestamp_epoch DESC
                    ) AS rn
                FROM input_prices
            )
            WHERE rn = 1;
        """)

        _create_token_minute_prices(db)

        actual = db.rows("""
            SELECT * FROM token_minute_prices
            ORDER BY clob_token_id, odds_minute_epoch
        """)
        expected = db.rows("""
            SELECT * FROM token_minute_reference
            ORDER BY clob_token_id, odds_minute_epoch
        """)
        assert actual == expected
    finally:
        db.close()

def test_stage_invariants_report_duplicate_token_minutes(tmp_path: Path) -> None:
    db = DuckDB(tmp_path / "invariants.duckdb")
    try:
        db.execute("""
            CREATE TABLE token_minute_prices AS
            SELECT 'a' AS clob_token_id, 0::BIGINT AS odds_minute_epoch
            UNION ALL
            SELECT 'a', 0::BIGINT
        """)
        with pytest.raises(RuntimeError, match="duplicate token-minute rows: 1"):
            _validate_token_minute_prices(db)
    finally:
        db.close()

def test_stage_invariants_report_duplicate_final_edges(tmp_path: Path) -> None:
    db = DuckDB(tmp_path / "edge_invariants.duckdb")
    try:
        db.execute("""
            CREATE TABLE logic_edges_v AS
            SELECT 'a' AS src_node_id, 'b' AS dst_node_id, 'implies' AS edge_type
            UNION ALL
            SELECT 'a', 'b', 'implies';

            CREATE TABLE price_edges_v AS
            SELECT 'c' AS src_node_id, 'd' AS dst_node_id, 'equivalent' AS edge_type
            WHERE false;
        """)
        with pytest.raises(RuntimeError, match="duplicate logic edges: 1"):
            _validate_final_edge_invariants(db)
    finally:
        db.close()

def test_internal_contract_validation_reports_drift(tmp_path: Path) -> None:
    db = DuckDB(tmp_path / "contracts.duckdb")
    try:
        db.execute("CREATE TABLE token_minute_prices AS SELECT 'a' AS clob_token_id")
        with pytest.raises(RuntimeError, match="token_minute_prices column contract drift"):
            validate_relation_columns(db, "token_minute_prices")
    finally:
        db.close()
