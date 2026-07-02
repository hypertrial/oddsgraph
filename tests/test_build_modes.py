from __future__ import annotations

import json
from pathlib import Path

import pytest

from oddsgraph.build import build
from oddsgraph.cli import main
from oddsgraph.queries import DuckDB, q


def test_build_can_skip_prices_and_keep_query_artifacts(
    synthetic_input: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "out"
    build(synthetic_input, out, write_prices=False)

    manifest = json.loads((out / "build_manifest.json").read_text())
    assert manifest["build_options"]["write_prices"] is False
    assert "prices.parquet" not in manifest["artifacts"]
    assert not (out / "prices.parquet").exists()

    assert main(["search", "--out", str(out), "--query", "Equivalent A"]) == 0
    assert "Will Equivalent A happen?" in capsys.readouterr().out
    assert main(["nodes", "--out", str(out), "--top", "3"]) == 0
    assert "node_id" in capsys.readouterr().out
    assert main(["edges", "--out", str(out), "--top", "3"]) == 0
    assert "edge_type" in capsys.readouterr().out
    assert main(["explain", "--out", str(out), "--node", "comp:Yes"]) == 0
    assert "Same-Market Constraint" in capsys.readouterr().out

def test_build_can_skip_coherence_and_keep_conditionals(
    synthetic_input: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "out"
    build(synthetic_input, out, solve_coherence=False)

    manifest = json.loads((out / "build_manifest.json").read_text())
    assert manifest["build_options"]["solve_coherence"] is False
    assert "coherence.parquet" not in manifest["artifacts"]
    assert "coherence_repairs.parquet" not in manifest["artifacts"]
    assert not (out / "coherence.parquet").exists()
    assert not (out / "coherence_repairs.parquet").exists()

    db = DuckDB()
    try:
        global_violations = int(db.scalar(f"""
            SELECT count(*)
            FROM read_parquet('{q(out / "violations.parquet")}')
            WHERE violation_type = 'global_incoherence'
        """))
        assert global_violations == 0
    finally:
        db.close()

    assert main(["violations", "--out", str(out), "--top", "5"]) == 0
    assert "violation_type" in capsys.readouterr().out
    assert main(["condition", "--out", str(out), "--a", "comp:Yes", "--b", "comp:No"]) == 0
    assert "exact_complement" in capsys.readouterr().out
    assert main(["coherence", "--out", str(out), "--top", "5"]) == 1
    assert "rebuild without --skip-coherence" in capsys.readouterr().err
    (out / "coherence.parquet").write_text("stale\n", encoding="utf-8")
    assert main(["coherence", "--out", str(out), "--top", "5"]) == 1
    assert "rebuild without --skip-coherence" in capsys.readouterr().err

def test_cli_build_can_skip_prices_and_coherence(synthetic_input: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert main([
        "build",
        "--input", str(synthetic_input),
        "--out", str(out),
        "--skip-prices",
        "--skip-coherence",
    ]) == 0

    manifest = json.loads((out / "build_manifest.json").read_text())
    assert manifest["build_options"] == {
        "fast_graph": False,
        "graph_lookback_days": 30,
        "solve_coherence": False,
        "write_prices": False,
    }
    assert "prices.parquet" not in manifest["artifacts"]
    assert "coherence.parquet" not in manifest["artifacts"]
    assert "coherence_repairs.parquet" not in manifest["artifacts"]
    assert not (out / "prices.parquet").exists()
    assert not (out / "coherence.parquet").exists()
    assert not (out / "coherence_repairs.parquet").exists()

def test_fast_graph_mode_keeps_query_artifacts(
    synthetic_input: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "out"
    assert main([
        "build",
        "--input", str(synthetic_input),
        "--out", str(out),
        "--fast-graph",
        "--graph-lookback-days", "1",
    ]) == 0

    manifest = json.loads((out / "build_manifest.json").read_text())
    assert manifest["build_options"] == {
        "fast_graph": True,
        "graph_lookback_days": 1,
        "solve_coherence": False,
        "write_prices": False,
    }
    assert manifest["stats"]["history_mode"] == "fast_graph_lookback"
    assert "prices.parquet" not in manifest["artifacts"]
    assert "coherence.parquet" not in manifest["artifacts"]
    assert not (out / "prices.parquet").exists()
    assert not (out / "coherence.parquet").exists()

    db = DuckDB()
    try:
        active_minutes = int(db.scalar(f"""
            SELECT active_minutes
            FROM read_parquet('{q(out / "nodes.parquet")}')
            WHERE node_id = 'comp:Yes'
        """) or 0)
    finally:
        db.close()
    assert active_minutes == 1

    assert main(["search", "--out", str(out), "--query", "Complement"]) == 0
    assert "Will Complement pass?" in capsys.readouterr().out
    assert main(["edges", "--out", str(out), "--top", "3"]) == 0
    assert "edge_type" in capsys.readouterr().out
    assert main(["condition", "--out", str(out), "--a", "comp:Yes", "--b", "comp:No"]) == 0
    assert "exact_complement" in capsys.readouterr().out
    assert main(["explain", "--out", str(out), "--node", "comp:Yes"]) == 0
    assert "Same-Market Constraint" in capsys.readouterr().out

def test_graph_lookback_days_requires_fast_graph(synthetic_input: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([
        "build",
        "--input", str(synthetic_input),
        "--out", str(tmp_path / "out"),
        "--graph-lookback-days", "1",
    ]) == 1
    assert "requires --fast-graph" in capsys.readouterr().err

    assert main([
        "build",
        "--input", str(synthetic_input),
        "--out", str(tmp_path / "out"),
        "--fast-graph",
        "--graph-lookback-days", "0",
    ]) == 1
    assert "must be positive" in capsys.readouterr().err
