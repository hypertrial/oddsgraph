from __future__ import annotations

from pathlib import Path

from .queries import DuckDB, q


REQUIRED_COLUMNS = {
    "market_id",
    "outcome_index",
    "clob_token_id",
    "question",
    "outcome_label",
    "event_slug",
    "is_active",
    "is_closed",
    "market_volume_usd",
    "ODDS_TIMESTAMP",
    "ODDS_TIMESTAMP_EPOCH",
    "price",
}

TABLE_REQUIRED_COLUMNS = {
    "market_id",
    "outcome_index",
    "clob_token_id",
    "question",
    "outcome_label",
    "event_slug",
    "is_active",
    "is_closed",
    "market_volume_usd",
    "odds_timestamp",
    "odds_timestamp_epoch",
    "price",
}


def validate_input(db: DuckDB, path: Path) -> None:
    validate_input_schema(db, path)
    db.execute(f"""
        CREATE OR REPLACE TEMP VIEW input_prices_validation AS
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
            ODDS_TIMESTAMP AS odds_timestamp,
            ODDS_TIMESTAMP_EPOCH AS odds_timestamp_epoch,
            CAST(floor(ODDS_TIMESTAMP_EPOCH / 60) * 60 AS BIGINT) AS odds_minute_epoch,
            price
        FROM read_parquet('{q(path)}');
    """)
    validate_input_table(db, "input_prices_validation")


def validate_input_schema(db: DuckDB, path: Path) -> None:
    rows = db.rows(f"SELECT name FROM parquet_schema('{q(path)}') WHERE name != 'duckdb_schema'")
    found = {row["name"] for row in rows}
    missing = sorted(REQUIRED_COLUMNS - found)
    if missing:
        raise ValueError("Input parquet missing required columns: " + ", ".join(missing))


def validate_input_table(db: DuckDB, table: str = "input_prices") -> None:
    failures = [
        ("null required values", _count(db, f"""
            SELECT count(*)
            FROM {table}
            WHERE {" OR ".join(f"{col} IS NULL" for col in sorted(TABLE_REQUIRED_COLUMNS))}
        """), "rows"),
        ("prices outside [0, 1]", _count(db, f"""
            SELECT count(*)
            FROM {table}
            WHERE price < 0 OR price > 1
        """), "rows"),
        ("duplicate token timestamp rows", _count(db, f"""
            SELECT count(*)
            FROM (
                SELECT clob_token_id, odds_timestamp_epoch
                FROM {table}
                GROUP BY 1, 2
                HAVING count(*) > 1
            )
        """), "groups"),
        ("unstable token metadata", _count(db, f"""
            SELECT count(*)
            FROM (
                SELECT clob_token_id
                FROM {table}
                GROUP BY clob_token_id
                HAVING count(DISTINCT market_id) > 1
                    OR count(DISTINCT outcome_index) > 1
                    OR count(DISTINCT question) > 1
                    OR count(DISTINCT outcome_label) > 1
                    OR count(DISTINCT event_slug) > 1
                    OR count(DISTINCT is_active) > 1
                    OR count(DISTINCT is_closed) > 1
                    OR count(DISTINCT market_volume_usd) > 1
            )
        """), "tokens"),
        ("markets with fewer than 2 tokens", _count(db, f"""
            SELECT count(*)
            FROM (
                SELECT market_id
                FROM {table}
                GROUP BY market_id
                HAVING count(DISTINCT clob_token_id) < 2
            )
        """), "markets"),
        ("markets without complete current minute", _count(db, f"""
            WITH market_tokens AS (
                SELECT market_id, count(DISTINCT clob_token_id) AS expected_tokens
                FROM {table}
                GROUP BY market_id
            ),
            complete_markets AS (
                SELECT c.market_id
                FROM (
                    SELECT
                        market_id,
                        odds_minute_epoch,
                        count(DISTINCT clob_token_id) AS token_count
                    FROM {table}
                    GROUP BY 1, 2
                ) c
                JOIN market_tokens t USING (market_id)
                WHERE c.token_count = t.expected_tokens
                GROUP BY c.market_id
            )
            SELECT count(*)
            FROM market_tokens t
            LEFT JOIN complete_markets c USING (market_id)
            WHERE c.market_id IS NULL
        """), "markets"),
    ]
    failed = [f"{name}: {count} {unit}" for name, count, unit in failures if count]
    if failed:
        raise ValueError("Input parquet failed validation: " + "; ".join(failed))


def _count(db: DuckDB, sql: str) -> int:
    return int(db.scalar(sql) or 0)
