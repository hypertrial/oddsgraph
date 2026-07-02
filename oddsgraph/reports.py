from __future__ import annotations

from pathlib import Path

from .queries import DuckDB


def write_reports(db: DuckDB, out_dir: Path, stats: dict[str, object]) -> None:
    reports = out_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    _write(reports / "summary.md", _summary(stats))
    _write(reports / "top_complement_violations.md", _query_report(db, "Top Complement Violations", """
        SELECT violation_id, severity, current_gap, mean_gap, src_node_id, dst_node_id
        FROM violations_v
        WHERE violation_type = 'complement_violation'
        ORDER BY current_gap DESC, mean_gap DESC
        LIMIT 50
    """))
    _write(reports / "strongest_implications.md", _query_report(db, "Strongest Implications", """
        SELECT
            e.src_node_id,
            e.dst_node_id,
            e.edge_basis,
            s.canonical_proposition AS src_proposition,
            d.canonical_proposition AS dst_proposition,
            e.confidence,
            e.violation_score,
            e.overlap_minutes,
            e.current_p_src,
            e.current_p_dst
        FROM logic_edges_v e
        JOIN nodes_v s ON s.node_id = e.src_node_id
        JOIN nodes_v d ON d.node_id = e.dst_node_id
        WHERE e.edge_type = 'implies'
        ORDER BY e.confidence DESC, e.overlap_minutes DESC
        LIMIT 50
    """))
    _write(reports / "strongest_exclusions.md", _query_report(db, "Strongest Exclusions", """
        SELECT
            e.src_node_id,
            e.dst_node_id,
            e.edge_basis,
            s.canonical_proposition AS src_proposition,
            d.canonical_proposition AS dst_proposition,
            e.confidence,
            e.violation_score,
            e.overlap_minutes,
            e.current_p_src,
            e.current_p_dst
        FROM logic_edges_v e
        JOIN nodes_v s ON s.node_id = e.src_node_id
        JOIN nodes_v d ON d.node_id = e.dst_node_id
        WHERE e.edge_type = 'mutually_exclusive'
        ORDER BY e.confidence DESC, e.overlap_minutes DESC
        LIMIT 50
    """))
    _write(reports / "duplicate_candidates.md", _query_report(db, "Duplicate Candidates", """
        SELECT src_node_id, dst_node_id, candidate_source, candidate_score, market_id_src, market_id_dst
        FROM candidate_edges_v
        WHERE candidate_source = 'exact_duplicate_same_event'
        ORDER BY candidate_score DESC
        LIMIT 50
    """))
    _write(reports / "price_only_edges.md", _query_report(db, "Price-Only Edges", """
        SELECT
            e.edge_type,
            e.src_node_id,
            e.dst_node_id,
            s.canonical_proposition AS src_proposition,
            d.canonical_proposition AS dst_proposition,
            e.confidence,
            e.score,
            e.overlap_minutes,
            e.current_p_src,
            e.current_p_dst
        FROM price_edges_v e
        JOIN nodes_v s ON s.node_id = e.src_node_id
        JOIN nodes_v d ON d.node_id = e.dst_node_id
        ORDER BY e.confidence DESC, e.overlap_minutes DESC
        LIMIT 50
    """))
    _write(reports / "coverage.md", _coverage_report(db))
    _write(reports / "conditional_examples.md", _query_report(db, "Conditional Examples", """
        SELECT a_node_id, b_node_id, method, p_a_given_b, lower_bound, upper_bound, confidence
        FROM conditional_edges_v
        ORDER BY confidence DESC, method
        LIMIT 50
    """))


def _summary(stats: dict[str, object]) -> str:
    lines = ["# oddsgraph build summary", ""]
    for key in (
        "input_rows",
        "markets",
        "tokens",
        "time_range_start",
        "time_range_end",
        "active_markets",
        "closed_markets",
        "candidate_edges",
        "logic_edges",
        "price_edges",
        "derived_edges",
        "violations",
        "incoherent_events",
        "runtime_seconds",
    ):
        lines.append(f"- **{key}:** {stats.get(key)}")
    return "\n".join(lines) + "\n"


def _coverage_report(db: DuckDB) -> str:
    lines = ["# Coverage", ""]
    _append_table(lines, "Market Families", db.rows("""
        SELECT
            market_family,
            count(DISTINCT market_id) AS markets,
            count(*) AS nodes,
            max(market_volume_usd) AS max_market_volume_usd
        FROM nodes_v
        GROUP BY market_family
        ORDER BY markets DESC, market_family
    """))
    _append_table(lines, "Candidate Sources", db.rows("""
        SELECT candidate_source, candidate_type, count(*) AS candidates
        FROM candidate_edges_v
        GROUP BY 1, 2
        ORDER BY candidates DESC, candidate_source, candidate_type
    """))
    _append_table(lines, "Logic Edges", db.rows("""
        SELECT edge_basis, edge_type, count(*) AS edges
        FROM logic_edges_v
        GROUP BY 1, 2
        ORDER BY edges DESC, edge_basis, edge_type
    """))
    _append_table(lines, "Price-Only Edges", db.rows("""
        SELECT edge_type, count(*) AS edges
        FROM price_edges_v
        GROUP BY edge_type
        ORDER BY edges DESC, edge_type
    """))
    _append_table(lines, "Top Unknown Markets", db.rows("""
        SELECT
            market_id,
            any_value(event_slug) AS event_slug,
            any_value(question) AS question,
            max(market_volume_usd) AS market_volume_usd,
            count(*) AS nodes
        FROM nodes_v
        WHERE market_family = 'unknown'
        GROUP BY market_id
        ORDER BY market_volume_usd DESC, market_id
        LIMIT 25
    """))
    _append_table(lines, "High-Confidence Price-Only Edges", db.rows("""
        SELECT
            e.edge_type,
            e.confidence,
            e.score,
            e.overlap_minutes,
            e.src_node_id,
            e.dst_node_id,
            s.canonical_proposition AS src_proposition,
            d.canonical_proposition AS dst_proposition
        FROM price_edges_v e
        JOIN nodes_v s ON s.node_id = e.src_node_id
        JOIN nodes_v d ON d.node_id = e.dst_node_id
        ORDER BY e.confidence DESC, e.overlap_minutes DESC
        LIMIT 25
    """))
    return "\n".join(lines) + "\n"


def _query_report(db: DuckDB, title: str, sql: str) -> str:
    rows = db.rows(sql)
    lines = [f"# {title}", ""]
    if not rows:
        return "\n".join(lines + ["No rows.", ""])
    lines.extend(markdown_table(rows))
    return "\n".join(lines) + "\n"


def _append_table(lines: list[str], title: str, rows: list[dict[str, object]]) -> None:
    lines.extend([f"## {title}", ""])
    if not rows:
        lines.extend(["No rows.", ""])
        return
    lines.extend(markdown_table(rows))
    lines.append("")


def markdown_table(rows: list[dict[str, object]], columns: list[str] | None = None) -> list[str]:
    cols = columns or list(rows[0])
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(row.get(col)) for col in cols) + " |")
    return lines


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|") if value is not None else ""


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
