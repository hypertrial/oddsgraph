from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import thresholds as T
from .queries import DuckDB, q
from .sql import create_table_from_rows_sql


@dataclass(frozen=True)
class EffectiveThresholds:
    equivalence_mean_abs_diff_max: float
    equivalence_current_abs_diff_max: float
    implication_violation_mean_max: float
    implication_current_slack: float
    exclusion_violation_mean_max: float
    exclusion_current_sum_max: float
    complement_current_gap_violation_min: float
    complement_mean_gap_violation_min: float


CALIBRATION_COLUMNS = [
    "bucket_id",
    "volume_min",
    "volume_max",
    "sample_count",
    "complement_p50",
    "complement_p95",
    "equivalence_p95",
    "implication_p95",
    "exclusion_p95",
]

CALIBRATION_EMPTY_TYPES = {
    "bucket_id": "INTEGER",
    "volume_min": "DOUBLE",
    "volume_max": "DOUBLE",
    "sample_count": "BIGINT",
    "complement_p50": "DOUBLE",
    "complement_p95": "DOUBLE",
    "equivalence_p95": "DOUBLE",
    "implication_p95": "DOUBLE",
    "exclusion_p95": "DOUBLE",
}

SCORED_EDGE_COLUMNS = [
    "src_node_id",
    "dst_node_id",
    "candidate_type",
    "edge_type",
    "edge_basis",
    "confidence",
    "score",
    "violation_score",
    "overlap_minutes",
    "current_p_src",
    "current_p_dst",
    "mean_p_src",
    "mean_p_dst",
    "market_id_src",
    "market_id_dst",
    "event_slug_src",
    "event_slug_dst",
    "evidence",
]

SCORED_EDGE_EMPTY_TYPES = {
    "src_node_id": "VARCHAR",
    "dst_node_id": "VARCHAR",
    "candidate_type": "VARCHAR",
    "edge_type": "VARCHAR",
    "edge_basis": "VARCHAR",
    "confidence": "DOUBLE",
    "score": "DOUBLE",
    "violation_score": "DOUBLE",
    "overlap_minutes": "BIGINT",
    "current_p_src": "DOUBLE",
    "current_p_dst": "DOUBLE",
    "mean_p_src": "DOUBLE",
    "mean_p_dst": "DOUBLE",
    "market_id_src": "VARCHAR",
    "market_id_dst": "VARCHAR",
    "event_slug_src": "VARCHAR",
    "event_slug_dst": "VARCHAR",
    "evidence": "VARCHAR",
}


def default_thresholds() -> EffectiveThresholds:
    return EffectiveThresholds(
        equivalence_mean_abs_diff_max=T.EQUIVALENCE_MEAN_ABS_DIFF_MAX,
        equivalence_current_abs_diff_max=T.EQUIVALENCE_CURRENT_ABS_DIFF_MAX,
        implication_violation_mean_max=T.IMPLICATION_VIOLATION_MEAN_MAX,
        implication_current_slack=T.IMPLICATION_CURRENT_SLACK,
        exclusion_violation_mean_max=T.EXCLUSION_VIOLATION_MEAN_MAX,
        exclusion_current_sum_max=T.EXCLUSION_CURRENT_SUM_MAX,
        complement_current_gap_violation_min=T.COMPLEMENT_CURRENT_GAP_VIOLATION_MIN,
        complement_mean_gap_violation_min=T.COMPLEMENT_MEAN_GAP_VIOLATION_MIN,
    )


def fit_calibration(db: DuckDB, out_dir: Path) -> tuple[list[dict[str, Any]], EffectiveThresholds]:
    complement_errors = db.rows("""
        SELECT
            c.src_node_id,
            c.dst_node_id,
            n.market_volume_usd AS volume,
            s.complement_error_raw AS error
        FROM candidate_edges_v c
        JOIN aligned_edges s USING (src_node_id, dst_node_id, candidate_type)
        JOIN nodes_v n ON n.node_id = c.src_node_id
        WHERE c.candidate_type = 'complement'
            AND s.complement_error_raw IS NOT NULL
        ORDER BY volume
    """)

    calibration_rows: list[dict[str, Any]] = []
    if not complement_errors:
        effective = default_thresholds()
        db.execute("""
            CREATE TABLE calibration_v AS
            SELECT 1::INTEGER AS bucket_id, 0.0::DOUBLE AS volume_min, 0.0::DOUBLE AS volume_max,
                0::BIGINT AS sample_count, 0.0::DOUBLE AS complement_p50, 0.0::DOUBLE AS complement_p95,
                0.0::DOUBLE AS equivalence_p95, 0.0::DOUBLE AS implication_p95, 0.0::DOUBLE AS exclusion_p95
            WHERE false
        """)
        db.execute(f"COPY calibration_v TO '{q(out_dir / 'calibration.parquet')}' (FORMAT PARQUET);")
        return calibration_rows, effective

    n = len(complement_errors)
    bucket_size = max(1, n // T.NUM_LIQUIDITY_BUCKETS)
    bucket_errors: dict[int, list[float]] = {i: [] for i in range(1, T.NUM_LIQUIDITY_BUCKETS + 1)}
    bucket_volumes: dict[int, list[float]] = {i: [] for i in range(1, T.NUM_LIQUIDITY_BUCKETS + 1)}

    for idx, row in enumerate(complement_errors):
        bucket_id = min(T.NUM_LIQUIDITY_BUCKETS, idx // bucket_size + 1)
        bucket_errors[bucket_id].append(float(row["error"]))
        bucket_volumes[bucket_id].append(float(row["volume"] or 0))

    p95_values: list[float] = []
    p50_values: list[float] = []
    for bucket_id in range(1, T.NUM_LIQUIDITY_BUCKETS + 1):
        errors = sorted(bucket_errors[bucket_id])
        volumes = bucket_volumes[bucket_id]
        if not errors:
            continue
        p50 = _quantile(errors, 0.5)
        p95 = _quantile(errors, T.CALIBRATION_QUANTILE)
        p95_values.append(p95)
        p50_values.append(p50)
        calibration_rows.append({
            "bucket_id": bucket_id,
            "volume_min": min(volumes),
            "volume_max": max(volumes),
            "sample_count": len(errors),
            "complement_p50": p50,
            "complement_p95": p95,
            "equivalence_p95": p95,
            "implication_p95": p95,
            "exclusion_p95": p95,
        })

    mid_p95 = _quantile(p95_values, 0.5) if p95_values else T.COMPLEMENT_CURRENT_GAP_VIOLATION_MIN
    mid_p50 = _quantile(p50_values, 0.5) if p50_values else T.COMPLEMENT_MEAN_GAP_VIOLATION_MIN
    effective = EffectiveThresholds(
        equivalence_mean_abs_diff_max=max(T.EQUIVALENCE_MEAN_ABS_DIFF_MAX, mid_p95),
        equivalence_current_abs_diff_max=max(T.EQUIVALENCE_CURRENT_ABS_DIFF_MAX, mid_p95 * 1.5),
        implication_violation_mean_max=max(T.IMPLICATION_VIOLATION_MEAN_MAX, mid_p95),
        implication_current_slack=max(T.IMPLICATION_CURRENT_SLACK, mid_p95 * 2),
        exclusion_violation_mean_max=max(T.EXCLUSION_VIOLATION_MEAN_MAX, mid_p95),
        exclusion_current_sum_max=max(T.EXCLUSION_CURRENT_SUM_MAX, 1.0 + mid_p95 * 2),
        complement_current_gap_violation_min=max(T.COMPLEMENT_CURRENT_GAP_VIOLATION_MIN, mid_p95),
        complement_mean_gap_violation_min=max(T.COMPLEMENT_MEAN_GAP_VIOLATION_MIN, mid_p50),
    )

    db.execute(create_table_from_rows_sql(
        "calibration_v",
        calibration_rows,
        CALIBRATION_COLUMNS,
        CALIBRATION_EMPTY_TYPES,
    ))
    db.execute(f"COPY calibration_v TO '{q(out_dir / 'calibration.parquet')}' (FORMAT PARQUET);")
    return calibration_rows, effective


def apply_calibration_confidence(db: DuckDB, effective: EffectiveThresholds) -> None:
    complement_errors = [
        float(row["error"])
        for row in db.rows("""
            SELECT s.complement_error_raw AS error
            FROM candidate_edges_v c
            JOIN aligned_edges s USING (src_node_id, dst_node_id, candidate_type)
            WHERE c.candidate_type = 'complement' AND s.complement_error_raw IS NOT NULL
        """)
    ]
    complement_errors.sort()

    scored = db.rows("""
        SELECT
            s.src_node_id,
            s.dst_node_id,
            s.candidate_type,
            s.edge_type,
            s.edge_basis,
            s.overlap_minutes,
            s.score,
            s.violation_score,
            s.current_p_src,
            s.current_p_dst,
            s.mean_p_src,
            s.mean_p_dst,
            s.market_id_src,
            s.market_id_dst,
            s.event_slug_src,
            s.event_slug_dst,
            s.evidence,
            CASE s.candidate_type
                WHEN 'complement' THEN s.complement_error_raw
                WHEN 'equivalence' THEN s.equivalence_error_raw
                WHEN 'implication' THEN s.implication_violation_raw
                WHEN 'mutual_exclusion' THEN s.exclusion_violation_raw
                ELSE NULL
            END AS observed_error
        FROM scored_edges_v s
    """)

    updated: list[dict[str, Any]] = []
    for row in scored:
        observed = row.get("observed_error")
        if row["candidate_type"] == "complement" and row["overlap_minutes"] < T.COMPLEMENT_LOW_OVERLAP_MINUTES:
            confidence = 0.5
        elif observed is None:
            confidence = 0.1
        elif len(complement_errors) < T.MIN_CALIBRATION_SAMPLES:
            confidence = max(0.05, 1.0 - 20.0 * float(observed))
        else:
            ge = sum(1 for e in complement_errors if e >= float(observed))
            confidence = 1.0 - ge / len(complement_errors)
        updated.append({**row, "confidence": confidence})

    db.execute("DROP TABLE IF EXISTS scored_edges_v")
    _load_rows(db, "scored_edges_v", updated, SCORED_EDGE_COLUMNS, SCORED_EDGE_EMPTY_TYPES)
    _rebuild_edge_tables(db, effective)


def thresholds_as_dict(effective: EffectiveThresholds) -> dict[str, float]:
    return asdict(effective)


def _rebuild_edge_tables(db: DuckDB, effective: EffectiveThresholds) -> None:
    db.execute(f"""
        CREATE OR REPLACE TABLE logic_edges_v AS
        SELECT
            src_node_id, dst_node_id, edge_type, edge_basis, confidence, score,
            violation_score, overlap_minutes, current_p_src, current_p_dst, mean_p_src,
            mean_p_dst, market_id_src, market_id_dst, event_slug_src, event_slug_dst, evidence
        FROM scored_edges_v
        WHERE edge_basis IN (
            'same_market', 'exact_duplicate', 'single_winner_family', 'stage_progression_rule'
        );

        CREATE OR REPLACE TABLE price_edges_v AS
        SELECT
            src_node_id, dst_node_id, edge_type, edge_basis, confidence, score,
            violation_score, overlap_minutes, current_p_src, current_p_dst, mean_p_src,
            mean_p_dst, market_id_src, market_id_dst, event_slug_src, event_slug_dst, evidence
        FROM scored_edges_v s
        WHERE s.edge_basis = 'price_only'
            AND (
                (
                    s.edge_type = 'equivalent'
                    AND s.overlap_minutes >= {T.MIN_OVERLAP_MINUTES}
                    AND s.score <= {effective.equivalence_mean_abs_diff_max}
                    AND abs(s.current_p_src - s.current_p_dst) <= {effective.equivalence_current_abs_diff_max}
                )
                OR (
                    s.edge_type = 'implies'
                    AND s.overlap_minutes >= {T.MIN_OVERLAP_MINUTES}
                    AND s.violation_score <= {effective.implication_violation_mean_max}
                    AND s.current_p_src <= s.current_p_dst + {effective.implication_current_slack}
                )
                OR (
                    s.edge_type = 'mutually_exclusive'
                    AND s.overlap_minutes >= {T.MIN_OVERLAP_MINUTES}
                    AND s.violation_score <= {effective.exclusion_violation_mean_max}
                    AND s.current_p_src + s.current_p_dst <= {effective.exclusion_current_sum_max}
                )
            )
            AND NOT EXISTS (
                SELECT 1 FROM logic_edges_v l
                WHERE l.src_node_id = s.src_node_id
                    AND l.dst_node_id = s.dst_node_id
                    AND l.edge_type = s.edge_type
            );
    """)


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(q * len(ordered)))
    return ordered[idx]


def _load_rows(
    db: DuckDB,
    table: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    empty_types: dict[str, str],
) -> None:
    db.execute(create_table_from_rows_sql(table, rows, columns, empty_types))
