from __future__ import annotations

import json
from pathlib import Path

import pytest

from oddsgraph.benchmark import _comparison_deltas
from oddsgraph.cli import main
from oddsgraph.queries import DuckDB, q


def test_cli_smoke(synthetic_input: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"

    assert main([
        "build",
        "--input", str(synthetic_input),
        "--out", str(out),
        "--allow-stale-current",
    ]) == 0
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
    assert main(["evaluate", "--out", str(out)]) == 1
    assert "rebuild with --resolutions" in capsys.readouterr().err
    assert main(["benchmark-summary", "--out", str(out)]) == 0
    captured = capsys.readouterr()
    assert "runtime_seconds:" in captured.out
    assert "top_stage_timings:" in captured.out

def test_cli_rejects_invalid_edge_type(tmp_path: Path) -> None:
    for command in ("edges", "price-edges"):
        with pytest.raises(SystemExit) as exc:
            main([command, "--out", str(tmp_path), "--edge-type", "bad"])
        assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        main([
            "explain-edge",
            "--out", str(tmp_path),
            "--src", "a",
            "--dst", "b",
            "--edge-type", "bad",
        ])
    assert exc.value.code == 2

def test_benchmark_compare_writes_json(
    synthetic_input: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_root = tmp_path / "benchmark"

    assert main([
        "benchmark-compare",
        "--input", str(synthetic_input),
        "--out-root", str(out_root),
        "--graph-lookback-days", "1",
    ]) == 0

    captured = capsys.readouterr()
    assert "benchmark_compare:" in captured.out
    assert "full" in captured.out
    assert "fast_graph" in captured.out
    data = json.loads((out_root / "benchmark_compare.json").read_text(encoding="utf-8"))
    assert data["modes"]["full"]["stats"]["history_mode"] == "full"
    assert data["modes"]["fast_graph"]["stats"]["history_mode"] == "fast_graph_lookback"


def test_benchmark_compare_deltas_match_numeric_fields() -> None:
    current = {
        "modes": {
            "full": {
                "stats": {"runtime_seconds": 12.5, "logic_edges": 5},
                "artifact_count": 13,
            }
        }
    }
    baseline = {
        "modes": {
            "full": {
                "stats": {"runtime_seconds": 10.0, "logic_edges": 4},
                "artifact_count": 12,
            }
        }
    }

    assert _comparison_deltas(current, baseline) == {
        "full": {"runtime_seconds": 2.5, "logic_edges": 1, "artifact_count": 1}
    }


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

def test_search_treats_like_wildcards_and_quotes_as_literal_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "cli_fixture"
    _write_cli_param_fixture(out)

    assert main(["search", "--out", str(out), "--query", "%"]) == 0
    captured = capsys.readouterr()
    assert "literal%_node" in captured.out
    assert "quote'node" not in captured.out

    assert main(["search", "--out", str(out), "--query", "_"]) == 0
    captured = capsys.readouterr()
    assert "literal%_node" in captured.out
    assert "quote'node" not in captured.out

    assert main(["search", "--out", str(out), "--query", "quote'"]) == 0
    captured = capsys.readouterr()
    assert "quote'node" in captured.out

def test_condition_and_explain_accept_quoted_node_ids(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "cli_fixture"
    _write_cli_param_fixture(out)

    assert main([
        "condition",
        "--out", str(out),
        "--a", "quote'node",
        "--b", "literal%_node",
    ]) == 0
    captured = capsys.readouterr()
    assert "quoted_fixture" in captured.out

    assert main(["explain", "--out", str(out), "--node", "quote'node"]) == 0
    captured = capsys.readouterr()
    assert "Same-Market Constraint" in captured.out
    assert "literal%_node" in captured.out

def _write_cli_param_fixture(out: Path) -> None:
    out.mkdir()
    db = DuckDB(out / "fixture.duckdb")
    try:
        _copy_query(db, out, "nodes.parquet", """
            SELECT *
            FROM (VALUES
                (
                    'quote''node',
                    'm_cli',
                    0,
                    'Will Quote''s fixture resolve?',
                    'Quoted',
                    'cli-event',
                    'unknown',
                    0.40,
                    0.40,
                    120,
                    'Quote''s exact proposition'
                ),
                (
                    'literal%_node',
                    'm_cli',
                    1,
                    'Will literal %_ fixture resolve?',
                    'Literal',
                    'cli-event',
                    'unknown',
                    0.60,
                    0.60,
                    120,
                    'Literal %_ proposition'
                )
            ) AS t(
                node_id,
                market_id,
                outcome_index,
                question,
                outcome_label,
                event_slug,
                market_family,
                current_price,
                mean_price,
                active_minutes,
                canonical_proposition
            )
        """)
        _copy_query(db, out, "market_groups.parquet", """
            SELECT
                'm_cli' AS market_id,
                1.0::DOUBLE AS current_sum_price,
                1.0::DOUBLE AS mean_sum_price
        """)
        _copy_query(db, out, "logic_edges.parquet", _empty_edge_query())
        _copy_query(db, out, "price_edges.parquet", _empty_edge_query())
        _copy_query(db, out, "violations.parquet", """
            SELECT
                NULL::VARCHAR AS violation_type,
                NULL::DOUBLE AS severity,
                NULL::DOUBLE AS current_gap,
                NULL::DOUBLE AS mean_gap,
                NULL::VARCHAR AS src_node_id,
                NULL::VARCHAR AS dst_node_id,
                NULL::VARCHAR AS description
            WHERE false
        """)
        _copy_query(db, out, "conditional_edges.parquet", """
            SELECT
                'quote''node' AS a_node_id,
                'literal%_node' AS b_node_id,
                0.25::DOUBLE AS p_a_given_b,
                0.0::DOUBLE AS lower_bound,
                1.0::DOUBLE AS upper_bound,
                'quoted_fixture' AS method,
                0.90::DOUBLE AS confidence,
                to_timestamp(0) AS as_of_ts,
                'parameter fixture' AS evidence
        """)
    finally:
        db.close()

def _copy_query(db: DuckDB, out: Path, artifact: str, sql: str) -> None:
    db.execute(f"COPY ({sql}) TO '{q(out / artifact)}' (FORMAT PARQUET)")

def _empty_edge_query() -> str:
    return """
        SELECT
            NULL::VARCHAR AS edge_type,
            NULL::VARCHAR AS edge_basis,
            NULL::DOUBLE AS confidence,
            NULL::DOUBLE AS score,
            NULL::BIGINT AS overlap_minutes,
            NULL::VARCHAR AS src_node_id,
            NULL::VARCHAR AS dst_node_id,
            NULL::VARCHAR AS evidence
        WHERE false
    """
