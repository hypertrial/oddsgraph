from __future__ import annotations

from pathlib import Path

from oddsgraph.artifacts import ARTIFACT_COLUMNS
from oddsgraph.build import build
from oddsgraph.evaluate import _write_evaluation_report
from oddsgraph.queries import DuckDB, q
from oddsgraph.reports import markdown_table
from tests.synthetic import write_synthetic_resolutions


def test_evaluation_with_resolutions(synthetic_input: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    resolutions = tmp_path / "resolutions.parquet"
    write_synthetic_resolutions(resolutions)
    build(synthetic_input, out, resolutions_path=resolutions)
    assert (out / "evaluation.parquet").exists()
    assert (out / "reports" / "evaluation.md").exists()
    db = DuckDB()
    try:
        rows = db.rows(f"DESCRIBE SELECT * FROM read_parquet('{q(out / 'evaluation.parquet')}')")
        assert [row["column_name"] for row in rows] == ARTIFACT_COLUMNS["evaluation.parquet"]
    finally:
        db.close()

def test_markdown_table_and_evaluation_report_escape_pipes(tmp_path: Path) -> None:
    assert "a\\|b" in "\n".join(markdown_table([{"metric_type": "a|b"}]))

    _write_evaluation_report(
        tmp_path,
        [{"metric_type": "pipe|metric", "edge_count": 1, "value": 0.5}],
    )

    report = (tmp_path / "reports" / "evaluation.md").read_text(encoding="utf-8")
    assert "pipe\\|metric" in report
