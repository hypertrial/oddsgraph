from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from oddsgraph.build import build
from oddsgraph.cli import main
from oddsgraph.coherence import EventModel, LpConstraint, _solve_l1_repair
from oddsgraph.queries import DuckDB, q
from oddsgraph.rules import load_taxonomy
from oddsgraph.schema import validate_input
from oddsgraph.sql import sql_literal
from tests.synthetic import write_synthetic_resolutions


ARTIFACTS = {
    "nodes.parquet",
    "prices.parquet",
    "market_groups.parquet",
    "candidate_edges.parquet",
    "logic_edges.parquet",
    "price_edges.parquet",
    "derived_edges.parquet",
    "constraint_hyperedges.parquet",
    "conditional_edges.parquet",
    "violations.parquet",
    "calibration.parquet",
    "coherence.parquet",
    "coherence_repairs.parquet",
}

ARTIFACT_COLUMNS = {
    "nodes.parquet": [
        "node_id", "market_id", "outcome_index", "clob_token_id", "question",
        "outcome_label", "event_slug", "is_active", "is_closed", "market_volume_usd",
        "market_family", "canonical_proposition", "proposition_type", "expected_tokens",
        "first_seen_ts", "last_seen_ts", "active_minutes", "current_price", "current_price_devig",
        "mean_price", "mean_price_devig", "min_price", "max_price",
    ],
    "prices.parquet": [
        "node_id", "market_id", "odds_timestamp", "odds_timestamp_epoch", "price", "price_devig",
        "scoring_price", "is_active", "is_closed", "market_volume_usd", "logit_price", "price_return_1m",
    ],
    "market_groups.parquet": [
        "market_id", "event_slug", "question", "market_family", "num_tokens", "token_ids",
        "outcome_labels", "is_active", "is_closed", "market_volume_usd", "first_seen_ts",
        "last_seen_ts", "current_sum_price", "mean_sum_price",
    ],
    "candidate_edges.parquet": [
        "src_node_id", "dst_node_id", "candidate_type", "candidate_source", "candidate_score",
        "market_id_src", "market_id_dst", "event_slug_src", "event_slug_dst",
    ],
    "logic_edges.parquet": [
        "src_node_id", "dst_node_id", "edge_type", "edge_basis", "confidence", "score",
        "violation_score", "overlap_minutes", "current_p_src", "current_p_dst", "mean_p_src",
        "mean_p_dst", "market_id_src", "market_id_dst", "event_slug_src", "event_slug_dst", "evidence",
    ],
    "price_edges.parquet": [
        "src_node_id", "dst_node_id", "edge_type", "edge_basis", "confidence", "score",
        "violation_score", "overlap_minutes", "current_p_src", "current_p_dst", "mean_p_src",
        "mean_p_dst", "market_id_src", "market_id_dst", "event_slug_src", "event_slug_dst", "evidence",
    ],
    "derived_edges.parquet": [
        "src_node_id", "dst_node_id", "edge_type", "edge_basis", "confidence", "path", "evidence",
    ],
    "constraint_hyperedges.parquet": [
        "constraint_id", "constraint_type", "market_id", "event_slug", "question", "node_ids",
        "current_sum_price", "mean_sum_price", "expected_sum_price", "violation_score",
        "confidence", "evidence",
    ],
    "conditional_edges.parquet": [
        "a_node_id", "b_node_id", "p_a_given_b", "lower_bound", "upper_bound", "method",
        "confidence", "as_of_ts", "evidence",
    ],
    "violations.parquet": [
        "violation_id", "violation_type", "src_node_id", "dst_node_id", "market_id_src",
        "market_id_dst", "event_slug_src", "event_slug_dst", "severity", "current_gap",
        "mean_gap", "confidence", "first_seen_ts", "last_seen_ts", "description",
    ],
    "calibration.parquet": [
        "bucket_id", "volume_min", "volume_max", "sample_count", "complement_p50",
        "complement_p95", "equivalence_p95", "implication_p95", "exclusion_p95",
    ],
    "coherence.parquet": [
        "event_slug", "node_count", "constraint_count", "incoherence_distance", "solver_status",
    ],
    "coherence_repairs.parquet": [
        "event_slug", "node_id", "observed_price", "repaired_price", "adjustment",
    ],
}

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
        for artifact, expected in ARTIFACT_COLUMNS.items():
            rows = db.rows(f"DESCRIBE SELECT * FROM read_parquet('{q(synthetic_output / artifact)}')")
            assert [row["column_name"] for row in rows] == expected
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


def test_taxonomy_loader_round_trip() -> None:
    taxonomy = load_taxonomy()
    assert taxonomy.name == "wc2026"
    assert len(taxonomy.stage_rules) == 5
    assert "world-cup-winner" in taxonomy.single_winner_slugs


def test_lp_constraint_senses_preserve_feasible_observations() -> None:
    model = EventModel(
        "constraint-sense",
        ["a", "b", "c", "d"],
        pytest.importorskip("numpy").array([0.4, 0.6, 0.2, 0.2]),
        {"a": 0, "b": 1, "c": 2, "d": 3},
    )
    constraints = [
        LpConstraint("simplex", "eq", [(0, 1.0), (1, 1.0)], 1.0),
        LpConstraint("complement", "eq", [(0, 1.0), (1, 1.0)], 1.0),
        LpConstraint("equivalent", "eq", [(2, 1.0), (3, -1.0)], 0.0),
        LpConstraint("implies", "le", [(2, 1.0), (0, -1.0)], 0.0),
        LpConstraint("exclusion", "le", [(0, 1.0), (2, 1.0)], 1.0),
        LpConstraint("family_sum", "le", [(2, 1.0), (3, 1.0)], 1.0),
    ]

    repaired, distance, status = _solve_l1_repair(model, constraints)

    assert status == "optimal"
    assert distance == pytest.approx(0.0)
    assert list(repaired) == pytest.approx(list(model.observed))


def test_evaluation_with_resolutions(synthetic_input: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    resolutions = tmp_path / "resolutions.parquet"
    write_synthetic_resolutions(resolutions)
    build(synthetic_input, out, resolutions_path=resolutions)
    assert (out / "evaluation.parquet").exists()
    assert (out / "reports" / "evaluation.md").exists()


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


def test_cli_smoke(synthetic_input: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"

    assert main(["build", "--input", str(synthetic_input), "--out", str(out)]) == 0
    assert main(["search", "--out", str(out), "--query", "Equivalent A"]) == 0
    assert "Will Equivalent A happen?" in capsys.readouterr().out
    assert main(["coherence", "--out", str(out), "--top", "5"]) == 0
    assert "incoherence_distance" in capsys.readouterr().out
    assert main(["condition", "--out", str(out), "--a", "comp:Yes", "--b", "comp:No"]) == 0
    assert "exact_complement" in capsys.readouterr().out
    assert main(["condition", "--out", str(out), "--a", "NOT(Will Complement pass?)", "--b", "comp:Yes"]) == 0
    assert "exact_complement" in capsys.readouterr().out
    assert main(["condition", "--out", str(out), "--a", "Alpha", "--b", "comp:Yes"]) == 1
    captured = capsys.readouterr()
    assert "Ambiguous node query" in captured.err
    assert "Candidates:" in captured.err


def test_cli_explain_smoke(synthetic_output: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "--out", str(synthetic_output), "--node", "comp:Yes"]) == 0
    captured = capsys.readouterr()
    assert "Same-Market Constraint" in captured.out
    assert "comp:No" in captured.out

    assert main(["explain", "--out", str(synthetic_output), "--node", "Messi"]) == 0
    captured = capsys.readouterr()
    assert "Top goalscorer? :: Messi" in captured.out

    assert main(["explain", "--out", str(synthetic_output), "--node", "Alpha"]) == 1
    captured = capsys.readouterr()
    assert "Ambiguous node query" in captured.err
    assert "Candidates:" in captured.err

    assert main([
        "explain-edge",
        "--out", str(synthetic_output),
        "--src", "comp:No",
        "--dst", "comp:Yes",
        "--edge-type", "complement",
    ]) == 0
    captured = capsys.readouterr()
    assert "Logic Edge" in captured.out
    assert "same_market" in captured.out

    assert main([
        "explain-edge",
        "--out", str(synthetic_output),
        "--src", "eq_a:Yes",
        "--dst", "eq_b:Yes",
        "--edge-type", "equivalent",
    ]) == 0
    captured = capsys.readouterr()
    assert "Price-Only Edge" in captured.out
    assert "price_only" in captured.out

    assert main([
        "explain-edge",
        "--out", str(synthetic_output),
        "--src", "alpha_final:Yes",
        "--dst", "winner_alpha:Yes",
        "--edge-type", "implies",
    ]) == 0
    captured = capsys.readouterr()
    assert "stage_progression_rule" not in captured.out


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
