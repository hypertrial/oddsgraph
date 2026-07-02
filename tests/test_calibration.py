from __future__ import annotations

from pathlib import Path

import pytest

from oddsgraph.calibration import _empirical_confidence, apply_calibration_confidence, default_thresholds
from oddsgraph.queries import DuckDB


def test_empirical_confidence_counts_equal_errors_as_at_least_observed() -> None:
    errors = [0.1, 0.2, 0.2, 0.4]
    assert _empirical_confidence(errors, 0.2) == pytest.approx(0.25)
    assert _empirical_confidence(errors, 0.3) == pytest.approx(0.75)

def test_sql_calibration_confidence_counts_equal_errors_as_at_least_observed(tmp_path: Path) -> None:
    db = DuckDB(tmp_path / "calibration.duckdb")
    try:
        db.execute("""
            CREATE TABLE candidate_edges_v AS
            SELECT
                range AS sample_idx,
                'sample_src_' || range::VARCHAR AS src_node_id,
                'sample_dst_' || range::VARCHAR AS dst_node_id,
                'complement' AS candidate_type
            FROM range(50);

            CREATE TABLE aligned_edges AS
            SELECT
                src_node_id,
                dst_node_id,
                candidate_type,
                CASE
                    WHEN sample_idx < 10 THEN 0.1
                    WHEN sample_idx < 30 THEN 0.2
                    ELSE 0.4
                END AS complement_error_raw
            FROM candidate_edges_v;

            CREATE TABLE scored_edges_v AS
            SELECT
                'target_src' AS src_node_id,
                'target_dst' AS dst_node_id,
                'complement' AS candidate_type,
                'complement' AS edge_type,
                'same_market' AS edge_basis,
                0.0 AS confidence,
                0.2 AS score,
                0.2 AS violation_score,
                1000::BIGINT AS overlap_minutes,
                0.5 AS current_p_src,
                0.5 AS current_p_dst,
                0.5 AS mean_p_src,
                0.5 AS mean_p_dst,
                'm1' AS market_id_src,
                'm1' AS market_id_dst,
                'event-1' AS event_slug_src,
                'event-1' AS event_slug_dst,
                'test edge' AS evidence,
                0.2 AS complement_error_raw,
                NULL::DOUBLE AS equivalence_error_raw,
                NULL::DOUBLE AS implication_violation_raw,
                NULL::DOUBLE AS exclusion_violation_raw
            UNION ALL
            SELECT
                'float_src' AS src_node_id,
                'float_dst' AS dst_node_id,
                'implication' AS candidate_type,
                'implies' AS edge_type,
                'price_only' AS edge_basis,
                0.0 AS confidence,
                0.001 AS score,
                0.001 AS violation_score,
                1000::BIGINT AS overlap_minutes,
                0.225 AS current_p_src,
                0.205 AS current_p_dst,
                0.2 AS mean_p_src,
                0.3 AS mean_p_dst,
                'm2' AS market_id_src,
                'm3' AS market_id_dst,
                'event-2' AS event_slug_src,
                'event-2' AS event_slug_dst,
                'float boundary edge' AS evidence,
                NULL::DOUBLE AS complement_error_raw,
                NULL::DOUBLE AS equivalence_error_raw,
                0.001 AS implication_violation_raw,
                NULL::DOUBLE AS exclusion_violation_raw;
        """)

        apply_calibration_confidence(db, default_thresholds())

        confidence = float(db.scalar("SELECT confidence FROM scored_edges_v WHERE src_node_id = 'target_src'") or 0)
        assert confidence == pytest.approx(0.2)
        price_edges = int(db.scalar("SELECT count(*) FROM price_edges_v WHERE src_node_id = 'float_src'") or 0)
        assert price_edges == 1
    finally:
        db.close()
