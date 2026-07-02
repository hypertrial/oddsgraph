from __future__ import annotations

from pathlib import Path
from typing import Any

from .queries import DuckDB, q
from .sql import create_table_from_rows_sql


EVALUATION_COLUMNS = [
    "metric_type",
    "artifact",
    "edge_basis",
    "edge_type",
    "violation_type",
    "liquidity_bucket",
    "edge_count",
    "value",
]

EVALUATION_EMPTY_TYPES = {
    "metric_type": "VARCHAR",
    "artifact": "VARCHAR",
    "edge_basis": "VARCHAR",
    "edge_type": "VARCHAR",
    "violation_type": "VARCHAR",
    "liquidity_bucket": "INTEGER",
    "edge_count": "BIGINT",
    "value": "DOUBLE",
}


def run_evaluation(db: DuckDB, out_dir: Path, resolutions_path: Path) -> None:
    db.execute(f"""
        CREATE TABLE resolutions_input AS
        SELECT * FROM read_parquet('{q(resolutions_path)}');
    """)
    rows = _edge_validation_rows(db)
    rows.extend(_violation_followthrough_rows(db))
    rows.extend(_brier_rows(db))
    _write_evaluation(db, out_dir, rows)
    _write_evaluation_report(out_dir, rows)


def _edge_validation_rows(db: DuckDB) -> list[dict[str, Any]]:
    sql = """
        WITH resolved_nodes AS (
            SELECT
                n.node_id,
                n.market_id,
                coalesce(r.payout, CASE WHEN r.clob_token_id IS NOT NULL THEN r.payout END) AS payout
            FROM nodes_v n
            LEFT JOIN resolutions_input r
                ON r.clob_token_id = n.node_id
                OR (r.market_id = n.market_id AND r.outcome_label = n.outcome_label)
        ),
        edges AS (
            SELECT 'logic' AS artifact, edge_type, edge_basis, confidence, src_node_id, dst_node_id
            FROM logic_edges_v
            UNION ALL
            SELECT 'derived', edge_type, edge_basis, confidence, src_node_id, dst_node_id
            FROM derived_edges_v
            UNION ALL
            SELECT 'price', edge_type, edge_basis, confidence, src_node_id, dst_node_id
            FROM price_edges_v
        )
        SELECT
            e.artifact,
            e.edge_basis,
            e.edge_type,
            count(*) AS edge_count,
            avg(CASE
                WHEN e.edge_type = 'implies' THEN CASE WHEN s.payout <= d.payout THEN 1.0 ELSE 0.0 END
                WHEN e.edge_type = 'mutually_exclusive' THEN CASE WHEN s.payout + d.payout <= 1 THEN 1.0 ELSE 0.0 END
                WHEN e.edge_type = 'equivalent' THEN CASE WHEN s.payout = d.payout THEN 1.0 ELSE 0.0 END
                WHEN e.edge_type = 'complement' THEN CASE WHEN abs(s.payout + d.payout - 1) < 1e-9 THEN 1.0 ELSE 0.0 END
                ELSE NULL
            END) AS precision_rate
        FROM edges e
        JOIN resolved_nodes s ON s.node_id = e.src_node_id
        JOIN resolved_nodes d ON d.node_id = e.dst_node_id
        WHERE s.payout IS NOT NULL AND d.payout IS NOT NULL
        GROUP BY 1, 2, 3
    """
    return [
        {
            "metric_type": "edge_precision",
            "artifact": row["artifact"],
            "edge_basis": row["edge_basis"],
            "edge_type": row["edge_type"],
            "edge_count": row["edge_count"],
            "value": row["precision_rate"],
        }
        for row in db.rows(sql)
    ]


def _violation_followthrough_rows(db: DuckDB) -> list[dict[str, Any]]:
    return [
        {
            "metric_type": "violation_followthrough",
            "violation_type": row["violation_type"],
            "edge_count": row["count"],
            "value": row["resolved_rate"],
        }
        for row in db.rows("""
            SELECT
                violation_type,
                count(*) AS count,
                avg(CASE WHEN current_gap < mean_gap THEN 1.0 ELSE 0.0 END) AS resolved_rate
            FROM violations_v
            GROUP BY violation_type
        """)
    ]


def _brier_rows(db: DuckDB) -> list[dict[str, Any]]:
    return [
        {
            "metric_type": "brier",
            "liquidity_bucket": row["bucket_id"],
            "edge_count": row["count"],
            "value": row["brier"],
        }
        for row in db.rows("""
            WITH resolved AS (
                SELECT
                    n.node_id,
                    n.current_price,
                    r.payout,
                    n.market_volume_usd,
                    ntile(5) OVER (ORDER BY n.market_volume_usd) AS bucket_id
                FROM nodes_v n
                JOIN resolutions_input r
                    ON r.clob_token_id = n.node_id
                    OR (r.market_id = n.market_id AND r.outcome_label = n.outcome_label)
                WHERE r.payout IS NOT NULL AND n.current_price IS NOT NULL
            )
            SELECT bucket_id, count(*) AS count, avg(pow(current_price - payout, 2)) AS brier
            FROM resolved
            GROUP BY bucket_id
        """)
    ]


def _write_evaluation(db: DuckDB, out_dir: Path, rows: list[dict[str, Any]]) -> None:
    db.execute(create_table_from_rows_sql(
        "evaluation_v",
        rows,
        EVALUATION_COLUMNS,
        EVALUATION_EMPTY_TYPES,
    ))
    db.execute(f"COPY evaluation_v TO '{q(out_dir / 'evaluation.parquet')}' (FORMAT PARQUET);")


def _write_evaluation_report(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    reports = out_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    lines = ["# Evaluation", ""]
    if not rows:
        lines.append("No evaluation rows.")
    else:
        lines.append("| metric_type | artifact | edge_basis | edge_type | violation_type | liquidity_bucket | edge_count | value |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        for row in rows:
            lines.append(
                "| {metric_type} | {artifact} | {edge_basis} | {edge_type} | {violation_type} | {liquidity_bucket} | {edge_count} | {value} |".format(
                    metric_type=row.get("metric_type", ""),
                    artifact=row.get("artifact", ""),
                    edge_basis=row.get("edge_basis", ""),
                    edge_type=row.get("edge_type", ""),
                    violation_type=row.get("violation_type", ""),
                    liquidity_bucket=row.get("liquidity_bucket", ""),
                    edge_count=row.get("edge_count", ""),
                    value=row.get("value", ""),
                )
            )
    (reports / "evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
