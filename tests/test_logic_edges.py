from __future__ import annotations

import csv
from pathlib import Path

import pytest

from oddsgraph import thresholds as T
from oddsgraph.queries import DuckDB, q


ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_ORACLE = ROOT / "tests" / "fixtures" / "synthetic_edge_oracle.csv"
WC2026_ORACLE = ROOT / "tests" / "fixtures" / "wc2026_edge_oracle.csv"
WC2026_OUT = ROOT / "output" / "wc2026"


def _oracle_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _edge_set(out: Path) -> set[tuple[str, str, str]]:
    db = DuckDB()
    try:
        rows = db.rows(f"""
            SELECT src_node_id, dst_node_id, edge_type
            FROM read_parquet('{q(out / "logic_edges.parquet")}')
        """)
    finally:
        db.close()
    return {(row["src_node_id"], row["dst_node_id"], row["edge_type"]) for row in rows}


def _scalar(db: DuckDB, sql: str) -> int:
    return int(db.scalar(sql) or 0)


def _assert_logic_invariants(out: Path) -> None:
    db = DuckDB()
    logic = q(out / "logic_edges.parquet")
    try:
        checks = {
            "self edges": f"""
                SELECT count(*) FROM read_parquet('{logic}')
                WHERE src_node_id = dst_node_id
            """,
            "duplicate typed edges": f"""
                SELECT count(*)
                FROM (
                    SELECT src_node_id, dst_node_id, edge_type
                    FROM read_parquet('{logic}')
                    GROUP BY 1, 2, 3
                    HAVING count(*) > 1
                )
            """,
            "cross-market complements": f"""
                SELECT count(*) FROM read_parquet('{logic}')
                WHERE edge_type = 'complement' AND market_id_src != market_id_dst
            """,
            "low-overlap cross edges": f"""
                SELECT count(*) FROM read_parquet('{logic}')
                WHERE edge_type != 'complement'
                    AND overlap_minutes < {T.MIN_OVERLAP_MINUTES}
            """,
            "equivalence threshold breaches": f"""
                SELECT count(*) FROM read_parquet('{logic}')
                WHERE edge_type = 'equivalent'
                    AND (
                        score > {T.EQUIVALENCE_MEAN_ABS_DIFF_MAX}
                        OR abs(current_p_src - current_p_dst) > {T.EQUIVALENCE_CURRENT_ABS_DIFF_MAX}
                    )
            """,
            "implication threshold breaches": f"""
                SELECT count(*) FROM read_parquet('{logic}')
                WHERE edge_type = 'implies'
                    AND (
                        violation_score > {T.IMPLICATION_VIOLATION_MEAN_MAX}
                        OR current_p_src > current_p_dst + {T.IMPLICATION_CURRENT_SLACK}
                    )
            """,
            "exclusion threshold breaches": f"""
                SELECT count(*) FROM read_parquet('{logic}')
                WHERE edge_type = 'mutually_exclusive'
                    AND (
                        violation_score > {T.EXCLUSION_VIOLATION_MEAN_MAX}
                        OR current_p_src + current_p_dst > {T.EXCLUSION_CURRENT_SUM_MAX}
                    )
            """,
            "null required metadata": f"""
                SELECT count(*) FROM read_parquet('{logic}')
                WHERE confidence IS NULL
                    OR market_id_src IS NULL
                    OR market_id_dst IS NULL
                    OR event_slug_src IS NULL
                    OR event_slug_dst IS NULL
            """,
        }
        failures = {name: _scalar(db, sql) for name, sql in checks.items()}
    finally:
        db.close()
    assert failures == {name: 0 for name in checks}


def _resolve_node(db: DuckDB, out: Path, query: str) -> str:
    nodes = q(out / "nodes.parquet")
    exact = db.rows(f"""
        SELECT node_id
        FROM read_parquet('{nodes}')
        WHERE node_id = '{q(query)}'
    """)
    if exact:
        assert len(exact) == 1, query
        return exact[0]["node_id"]
    matches = db.rows(f"""
        SELECT node_id
        FROM read_parquet('{nodes}')
        WHERE lower(canonical_proposition) LIKE lower('%{q(query)}%')
            OR lower(question) LIKE lower('%{q(query)}%')
    """)
    assert len(matches) == 1, f"{query!r} resolved to {len(matches)} nodes"
    return matches[0]["node_id"]


def _wc2026_output_or_skip() -> Path:
    if not (WC2026_OUT / "logic_edges.parquet").exists():
        pytest.skip("output/wc2026 is not present")
    return WC2026_OUT


def test_edge_oracle_required_edges_present(synthetic_output: Path) -> None:
    edges = _edge_set(synthetic_output)
    required = [row for row in _oracle_rows(SYNTHETIC_ORACLE) if row["expectation"] == "required"]
    missing = [
        row for row in required
        if (row["src_node_id"], row["dst_node_id"], row["edge_type"]) not in edges
    ]
    assert missing == []


def test_edge_oracle_forbidden_edges_absent(synthetic_output: Path) -> None:
    edges = _edge_set(synthetic_output)
    forbidden = [row for row in _oracle_rows(SYNTHETIC_ORACLE) if row["expectation"] == "forbidden"]
    present = [
        row for row in forbidden
        if (row["src_node_id"], row["dst_node_id"], row["edge_type"]) in edges
    ]
    assert present == []


def test_candidate_gates_reject_low_support_pairs(synthetic_output: Path) -> None:
    edges = _edge_set(synthetic_output)
    gated_pairs = [
        ("low_volume_a:Yes", "low_volume_b:Yes"),
        ("low_active_a:Yes", "low_active_b:Yes"),
        ("low_overlap_a:Yes", "low_overlap_b:Yes"),
        ("diff_event_a:Yes", "diff_event_b:Yes"),
    ]
    cross_types = {"equivalent", "implies", "mutually_exclusive"}
    leaked = [
        (a, b, edge_type)
        for src, dst in gated_pairs
        for a, b in ((src, dst), (dst, src))
        for edge_type in cross_types
        if (a, b, edge_type) in edges
    ]
    assert leaked == []


def test_threshold_boundaries_are_precision_first(synthetic_output: Path) -> None:
    edges = _edge_set(synthetic_output)
    assert ("eq_a:Yes", "eq_b:Yes", "equivalent") in edges
    assert ("eq_shift_a:Yes", "eq_shift_b:Yes", "equivalent") not in edges
    assert ("eq_spike_a:Yes", "eq_spike_b:Yes", "equivalent") not in edges
    assert ("imp_a:Yes", "imp_b:Yes", "implies") in edges
    assert ("imp_current_bad_a:Yes", "imp_current_bad_b:Yes", "implies") not in edges
    assert ("excl_a:Yes", "excl_b:Yes", "mutually_exclusive") in edges
    assert ("excl_current_bad_a:Yes", "excl_current_bad_b:Yes", "mutually_exclusive") not in edges


def test_implication_is_directional(synthetic_output: Path) -> None:
    edges = _edge_set(synthetic_output)
    assert ("imp_a:Yes", "imp_b:Yes", "implies") in edges
    assert ("imp_b:Yes", "imp_a:Yes", "implies") not in edges


def test_full_output_invariants_on_synthetic_build(synthetic_output: Path) -> None:
    _assert_logic_invariants(synthetic_output)


@pytest.mark.full_output
def test_full_output_invariants_on_wc2026_if_available() -> None:
    _assert_logic_invariants(_wc2026_output_or_skip())


@pytest.mark.full_output
def test_wc2026_oracle_if_available() -> None:
    out = _wc2026_output_or_skip()
    edges = _edge_set(out)
    db = DuckDB()
    try:
        resolved = []
        for row in _oracle_rows(WC2026_ORACLE):
            resolved.append({
                **row,
                "src_node_id": _resolve_node(db, out, row["src_query"]),
                "dst_node_id": _resolve_node(db, out, row["dst_query"]),
            })
    finally:
        db.close()
    required_missing = [
        row for row in resolved
        if row["expectation"] == "required"
        and (row["src_node_id"], row["dst_node_id"], row["edge_type"]) not in edges
    ]
    forbidden_present = [
        row for row in resolved
        if row["expectation"] == "forbidden"
        and (row["src_node_id"], row["dst_node_id"], row["edge_type"]) in edges
    ]
    assert required_missing == []
    assert forbidden_present == []
