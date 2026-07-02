from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .build import build
from .queries import q
from .search import read_rows, resolve_node, search_nodes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oddsgraph")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build")
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)

    p = sub.add_parser("nodes")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--top", type=int, default=50)

    p = sub.add_parser("edges")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--edge-type", default=None)
    p.add_argument("--top", type=int, default=50)

    p = sub.add_parser("price-edges")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--edge-type", default=None)
    p.add_argument("--top", type=int, default=50)

    p = sub.add_parser("violations")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--top", type=int, default=50)

    p = sub.add_parser("condition")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--a", required=True)
    p.add_argument("--b", required=True)

    p = sub.add_parser("search")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--query", required=True)
    p.add_argument("--top", type=int, default=20)

    args = parser.parse_args(argv)
    try:
        if args.cmd == "build":
            stats = build(args.input, args.out)
            for key, value in stats.items():
                print(f"{key}: {value}")
        elif args.cmd == "nodes":
            _print_rows(read_rows(args.out, "nodes.parquet", f"""
                SELECT node_id, market_id, outcome_label, current_price, canonical_proposition
                FROM read_parquet('{{path}}')
                ORDER BY market_volume_usd DESC, current_price DESC NULLS LAST
                LIMIT {args.top}
            """))
        elif args.cmd == "edges":
            edge_filter = f"WHERE edge_type = '{q(args.edge_type)}'" if args.edge_type else ""
            _print_rows(read_rows(args.out, "logic_edges.parquet", f"""
                SELECT edge_type, edge_basis, confidence, score, overlap_minutes, src_node_id, dst_node_id
                FROM read_parquet('{{path}}')
                {edge_filter}
                ORDER BY confidence DESC, overlap_minutes DESC
                LIMIT {args.top}
            """))
        elif args.cmd == "price-edges":
            edge_filter = f"WHERE edge_type = '{q(args.edge_type)}'" if args.edge_type else ""
            _print_rows(read_rows(args.out, "price_edges.parquet", f"""
                SELECT edge_type, edge_basis, confidence, score, overlap_minutes, src_node_id, dst_node_id
                FROM read_parquet('{{path}}')
                {edge_filter}
                ORDER BY confidence DESC, overlap_minutes DESC
                LIMIT {args.top}
            """))
        elif args.cmd == "violations":
            _print_rows(read_rows(args.out, "violations.parquet", f"""
                SELECT violation_type, severity, current_gap, mean_gap, src_node_id, dst_node_id
                FROM read_parquet('{{path}}')
                ORDER BY current_gap DESC, mean_gap DESC
                LIMIT {args.top}
            """))
        elif args.cmd == "condition":
            a = resolve_node(args.out, args.a, require_unique=True)
            b = resolve_node(args.out, args.b, require_unique=True)
            if not a or not b:
                raise ValueError("Could not resolve both nodes")
            _print_rows(read_rows(args.out, "conditional_edges.parquet", f"""
                SELECT *
                FROM read_parquet('{{path}}')
                WHERE a_node_id = '{q(a)}' AND b_node_id = '{q(b)}'
                LIMIT 20
            """))
        elif args.cmd == "search":
            _print_rows(search_nodes(args.out, args.query, args.top))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_rows(rows: list[dict[str, object]]) -> None:
    if not rows:
        print("No rows.")
        return
    cols = list(rows[0])
    widths = {
        col: min(80, max(len(col), *(len(str(row.get(col, ""))) for row in rows)))
        for col in cols
    }
    print("  ".join(col.ljust(widths[col]) for col in cols))
    print("  ".join("-" * widths[col] for col in cols))
    for row in rows:
        print("  ".join(str(row.get(col, ""))[: widths[col]].ljust(widths[col]) for col in cols))


if __name__ == "__main__":
    raise SystemExit(main())
