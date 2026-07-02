from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from oddsgraph.artifacts import ARTIFACT_COLUMNS, ARTIFACT_EMPTY_TYPES, PARQUET_ARTIFACTS, artifact_projection
from oddsgraph.build import _validate_generated_artifacts, build
from oddsgraph.queries import DuckDB, q
from oddsgraph.rules import load_taxonomy


ARTIFACTS = set(PARQUET_ARTIFACTS)


def test_build_outputs_artifacts_and_core_logic(synthetic_output: Path) -> None:
    db = DuckDB()
    try:
        assert ARTIFACTS <= {p.name for p in synthetic_output.glob("*.parquet")}
        assert (synthetic_output / "reports" / "summary.md").read_text()
        coverage = (synthetic_output / "reports" / "coverage.md").read_text()
        assert "## Market Families" in coverage
        assert "## Candidate Sources" in coverage
        assert "## Logic Edges" in coverage
        assert "## Price-Only Edges" in coverage

        nodes = db.rows(f"""
            SELECT outcome_label, canonical_proposition
            FROM read_parquet('{q(synthetic_output / "nodes.parquet")}')
            WHERE market_id = 'named'
            ORDER BY outcome_label
        """)
        assert nodes == [
            {"outcome_label": "Messi", "canonical_proposition": "Top goalscorer? :: Messi"},
            {"outcome_label": "Ronaldo", "canonical_proposition": "Top goalscorer? :: Ronaldo"},
        ]

        nary = db.rows(f"""
            SELECT constraint_type, current_sum_price
            FROM read_parquet('{q(synthetic_output / "constraint_hyperedges.parquet")}')
            WHERE market_id = 'golden_boot'
        """)
        assert nary == [{"constraint_type": "one_of_n", "current_sum_price": pytest.approx(1.0)}]

        coherence = db.rows(f"""
            SELECT solver_status, incoherence_distance
            FROM read_parquet('{q(synthetic_output / "coherence.parquet")}')
            WHERE event_slug = 'world-cup-golden-boot-winner'
        """)
        assert coherence == [{"solver_status": "optimal", "incoherence_distance": pytest.approx(0.0)}]

        false_global_violations = int(db.scalar(f"""
            SELECT count(*)
            FROM read_parquet('{q(synthetic_output / "violations.parquet")}')
            WHERE violation_type = 'global_incoherence'
                AND event_slug_src = 'world-cup-golden-boot-winner'
        """))
        assert false_global_violations == 0

        current_sum = float(db.scalar(f"""
            SELECT current_sum_price
            FROM read_parquet('{q(synthetic_output / "market_groups.parquet")}')
            WHERE market_id = 'stale'
        """))
        assert current_sum == pytest.approx(1.0)

        market_groups = db.rows(f"""
            SELECT num_tokens, token_ids, outcome_labels
            FROM read_parquet('{q(synthetic_output / "market_groups.parquet")}')
        """)
        for row in market_groups:
            token_ids = row["token_ids"]
            outcome_labels = row["outcome_labels"]
            assert len(token_ids) == row["num_tokens"]
            assert len(outcome_labels) == row["num_tokens"]
            assert len(set(token_ids)) == len(token_ids)
            assert len(set(outcome_labels)) == len(outcome_labels)

        duplicate_candidates = int(db.scalar(f"""
            SELECT count(*)
            FROM (
                SELECT src_node_id, dst_node_id, candidate_type
                FROM read_parquet('{q(synthetic_output / 'candidate_edges.parquet')}')
                GROUP BY 1, 2, 3
                HAVING count(*) > 1
            )
        """))
        assert duplicate_candidates == 0

        violations = db.rows(f"""
            SELECT violation_type
            FROM read_parquet('{q(synthetic_output / "violations.parquet")}')
            WHERE market_id_src = 'bad'
        """)
        assert violations == [{"violation_type": "complement_violation"}]

        conditionals = db.rows(f"""
            SELECT p_a_given_b
            FROM read_parquet('{q(synthetic_output / "conditional_edges.parquet")}')
            WHERE method = 'exact_implication_reverse'
        """)
        assert all(row["p_a_given_b"] is None or row["p_a_given_b"] <= 1.0 for row in conditionals)

        methods = {
            row["method"]
            for row in db.rows(
                f"SELECT DISTINCT method FROM read_parquet('{q(synthetic_output / 'conditional_edges.parquet')}')"
            )
        }
        assert {
            "exact_complement",
            "exact_implication",
            "exact_implication_reverse",
            "exact_exclusion",
            "bounded_frechet",
        } <= methods
    finally:
        db.close()

def test_artifact_schemas_match_contract(synthetic_output: Path) -> None:
    db = DuckDB()
    try:
        for artifact in PARQUET_ARTIFACTS:
            expected = ARTIFACT_COLUMNS[artifact]
            rows = db.rows(f"DESCRIBE SELECT * FROM read_parquet('{q(synthetic_output / artifact)}')")
            assert [row["column_name"] for row in rows] == expected
    finally:
        db.close()

def test_artifact_empty_type_contracts_match_columns() -> None:
    for artifact, empty_types in ARTIFACT_EMPTY_TYPES.items():
        assert list(empty_types) == ARTIFACT_COLUMNS[artifact]

def test_artifact_projection_matches_contract() -> None:
    assert artifact_projection("logic_edges.parquet").split(", ") == ARTIFACT_COLUMNS["logic_edges.parquet"]
    assert artifact_projection("logic_edges.parquet", table_alias="e").split(", ") == [
        f"e.{column}" for column in ARTIFACT_COLUMNS["logic_edges.parquet"]
    ]

def test_generated_artifact_validation_reports_missing_files(tmp_path: Path) -> None:
    db = DuckDB()
    try:
        with pytest.raises(RuntimeError, match="Missing generated artifacts"):
            _validate_generated_artifacts(db, tmp_path, has_evaluation=False)
    finally:
        db.close()

def test_generated_artifact_validation_reports_schema_drift(
    synthetic_output: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    for artifact in PARQUET_ARTIFACTS:
        shutil.copy2(synthetic_output / artifact, out / artifact)
    db = DuckDB()
    try:
        db.execute(f"COPY (SELECT 'bad' AS node_id) TO '{q(out / 'nodes.parquet')}' (FORMAT PARQUET)")
        with pytest.raises(RuntimeError, match=r"nodes\.parquet schema drift"):
            _validate_generated_artifacts(db, out, has_evaluation=False)
    finally:
        db.close()

def test_semantic_rule_classification(synthetic_output: Path) -> None:
    db = DuckDB()
    try:
        families = {
            row["market_id"]: row["market_family"]
            for row in db.rows(f"""
                SELECT market_id, market_family
                FROM read_parquet('{q(synthetic_output / "market_groups.parquet")}')
                WHERE market_id IN ('comp', 'winner_alpha', 'alpha_final', 'alpha_semis', 'golden_boot')
            """)
        }
        assert families == {
            "comp": "unknown",
            "winner_alpha": "single_winner",
            "alpha_final": "stage_progression",
            "alpha_semis": "stage_progression",
            "golden_boot": "single_winner",
        }
        sources = {
            row["candidate_source"]
            for row in db.rows(f"""
                SELECT DISTINCT candidate_source
                FROM read_parquet('{q(synthetic_output / "candidate_edges.parquet")}')
            """)
        }
        assert {"exact_duplicate_same_event", "semantic_single_winner", "semantic_stage_progression"} <= sources
    finally:
        db.close()

def test_build_manifest_marks_success(synthetic_output: Path) -> None:
    manifest = json.loads((synthetic_output / "build_manifest.json").read_text())
    assert set(manifest["artifacts"]) == ARTIFACTS
    assert manifest["stats"]["tokens"] > 0
    assert manifest["taxonomy"]["name"] == "wc2026"
    assert manifest["effective_thresholds"] is not None
    assert manifest["build_options"] == {
        "fast_graph": False,
        "graph_lookback_days": 30,
        "solve_coherence": True,
        "write_prices": True,
    }
    assert manifest["stats"]["history_mode"] == "full"
    assert manifest["stage_timings"]["create_input_prices"] >= 0
    assert manifest["stage_timings"]["token_minute_prices"] >= 0
    assert "reports/summary.md" in manifest["reports"]
    assert "reports/coverage.md" in manifest["reports"]
    db = DuckDB()
    try:
        for stat_key, artifact in (
            ("logic_edges", "logic_edges.parquet"),
            ("price_edges", "price_edges.parquet"),
        ):
            artifact_count = int(db.scalar(f"""
                SELECT count(*)
                FROM read_parquet('{q(synthetic_output / artifact)}')
            """))
            assert manifest["stats"][stat_key] == artifact_count
    finally:
        db.close()

def test_market_minute_sums_match_market_group_artifact(synthetic_output: Path) -> None:
    db = DuckDB(synthetic_output / "oddsgraph.duckdb")
    try:
        rows = db.rows(f"""
            WITH market_group_rows AS (
                SELECT market_id, current_sum_price, mean_sum_price
                FROM read_parquet('{q(synthetic_output / "market_groups.parquet")}')
            ),
            sum_rows AS (
                SELECT
                    market_id,
                    max(CASE WHEN is_current_complete THEN scoring_price_sum END) AS current_sum_price,
                    avg(scoring_price_sum) FILTER (WHERE is_complete) AS mean_sum_price
                FROM market_minute_sums
                GROUP BY market_id
            )
            SELECT
                g.market_id,
                g.current_sum_price AS artifact_current_sum_price,
                s.current_sum_price AS table_current_sum_price,
                g.mean_sum_price AS artifact_mean_sum_price,
                s.mean_sum_price AS table_mean_sum_price
            FROM market_group_rows g
            JOIN sum_rows s USING (market_id)
        """)
    finally:
        db.close()

    assert rows
    for row in rows:
        assert row["artifact_current_sum_price"] == pytest.approx(row["table_current_sum_price"])
        assert row["artifact_mean_sum_price"] == pytest.approx(row["table_mean_sum_price"])

def test_taxonomy_loader_round_trip() -> None:
    taxonomy = load_taxonomy()
    assert taxonomy.name == "wc2026"
    assert len(taxonomy.stage_rules) == 5
    assert "world-cup-winner" in taxonomy.single_winner_slugs

def test_failed_build_removes_success_manifest(tmp_path: Path) -> None:
    path = tmp_path / "bad.parquet"
    out = tmp_path / "out"
    out.mkdir()
    (out / "build_manifest.json").write_text("old\n", encoding="utf-8")
    db = DuckDB(tmp_path / "bad.duckdb")
    try:
        db.execute(f"COPY (SELECT 'm1' AS market_id) TO '{q(path)}' (FORMAT PARQUET)")
    finally:
        db.close()

    with pytest.raises(ValueError, match="missing required columns"):
        build(path, out)
    assert not (out / "build_manifest.json").exists()
