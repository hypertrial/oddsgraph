from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csr_matrix

from . import thresholds as T
from .artifacts import ARTIFACT_COLUMNS, ARTIFACT_EMPTY_TYPES, artifact_projection
from .contracts import validate_relation_columns
from .queries import DuckDB, q
from .sql import create_table_from_rows_sql, values_rows_sql


@dataclass(frozen=True)
class EventModel:
    event_slug: str
    node_ids: list[str]
    observed: np.ndarray
    index: dict[str, int]


@dataclass(frozen=True)
class LpConstraint:
    kind: str
    sense: str
    coeffs: list[tuple[int, float]]
    rhs: float


@dataclass(frozen=True)
class CoherenceInputs:
    event_nodes: dict[str, list[str]]
    current_prices: dict[str, float]
    market_nodes: dict[str, list[list[str]]]
    logic_edges: dict[tuple[str, str], list[tuple[str, str]]]
    derived_implications: dict[str, list[tuple[str, str]]]
    family_nodes: dict[str, list[str]]


DERIVED_EDGE_COLUMNS = ARTIFACT_COLUMNS["derived_edges.parquet"]
DERIVED_EDGE_EMPTY_TYPES = ARTIFACT_EMPTY_TYPES["derived_edges.parquet"]
COHERENCE_COLUMNS = ARTIFACT_COLUMNS["coherence.parquet"]
COHERENCE_EMPTY_TYPES = ARTIFACT_EMPTY_TYPES["coherence.parquet"]
REPAIR_COLUMNS = ARTIFACT_COLUMNS["coherence_repairs.parquet"]
REPAIR_EMPTY_TYPES = ARTIFACT_EMPTY_TYPES["coherence_repairs.parquet"]


def compute_transitive_closure(db: DuckDB, out_dir: Path) -> None:
    edges = db.rows("""
        SELECT src_node_id, dst_node_id, confidence, evidence
        FROM logic_edges_v
        WHERE edge_type = 'implies'
    """)
    graph: dict[str, set[str]] = defaultdict(set)
    meta: dict[tuple[str, str], dict[str, Any]] = {}
    for row in edges:
        src = row["src_node_id"]
        dst = row["dst_node_id"]
        graph[src].add(dst)
        meta[(src, dst)] = row

    derived: list[dict[str, Any]] = []
    for start in graph:
        visited: set[str] = set()
        queue: deque[tuple[str, list[str]]] = deque((n, [start, n]) for n in graph[start])
        while queue:
            node, path = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            for nxt in graph.get(node, ()):
                new_path = path + [nxt]
                if len(new_path) > 2:
                    src, dst = new_path[0], new_path[-1]
                    if (src, dst) not in meta:
                        base = meta.get((new_path[0], new_path[1]), {})
                        derived.append({
                            "src_node_id": src,
                            "dst_node_id": dst,
                            "edge_type": "implies",
                            "edge_basis": "transitive",
                            "confidence": float(base.get("confidence") or 0.5),
                            "path": "->".join(new_path),
                            "evidence": "transitive closure of accepted implications",
                        })
                        meta[(src, dst)] = derived[-1]
                queue.append((nxt, new_path))

    if derived:
        db.execute("CREATE TABLE derived_edges_v AS " + _derived_values_sql(derived))
    else:
        db.execute(create_table_from_rows_sql(
            "derived_edges_v",
            derived,
            DERIVED_EDGE_COLUMNS,
            DERIVED_EDGE_EMPTY_TYPES,
        ))
    validate_relation_columns(db, "derived_edges_v")
    db.execute(
        f"""
        COPY (
            SELECT {artifact_projection("derived_edges.parquet")}
            FROM derived_edges_v
        ) TO '{q(out_dir / 'derived_edges.parquet')}' (FORMAT PARQUET);
        """
    )


def solve_event_coherence(db: DuckDB, out_dir: Path) -> list[str]:
    warnings: list[str] = []
    inputs = _collect_coherence_inputs(db)
    coherence_rows: list[dict[str, Any]] = []
    repair_rows: list[dict[str, Any]] = []

    for slug, node_ids in inputs.event_nodes.items():
        if len(node_ids) > T.LP_MAX_NODES_PER_EVENT:
            warnings.append(f"skipped LP for {slug}: {len(node_ids)} nodes exceeds cap")
            continue
        model = EventModel(
            slug,
            node_ids,
            np.array([inputs.current_prices[n] for n in node_ids]),
            {n: i for i, n in enumerate(node_ids)},
        )
        constraints = _collect_constraints_from_inputs(inputs, model)
        if len(constraints) > T.LP_MAX_CONSTRAINTS_PER_EVENT:
            warnings.append(f"skipped LP for {slug}: {len(constraints)} constraints exceeds cap")
            continue
        if _constraints_satisfied(model, constraints):
            repaired, distance, status = model.observed.copy(), 0.0, "optimal"
        else:
            repaired, distance, status = _solve_l1_repair(model, constraints)
        if not math.isfinite(distance):
            distance = 1e6
        solver_status = "optimal" if status == "optimal" else "infeasible"
        coherence_rows.append({
            "event_slug": slug,
            "node_count": len(node_ids),
            "constraint_count": len(constraints),
            "incoherence_distance": distance,
            "solver_status": solver_status,
        })
        for node_id, obs, rep in zip(node_ids, model.observed, repaired):
            repair_rows.append({
                "event_slug": slug,
                "node_id": node_id,
                "observed_price": float(obs),
                "repaired_price": float(rep),
                "adjustment": float(rep - obs),
            })

    _write_table(db, out_dir / "coherence.parquet", "coherence_v", coherence_rows, COHERENCE_COLUMNS, COHERENCE_EMPTY_TYPES)
    _write_table(db, out_dir / "coherence_repairs.parquet", "coherence_repairs_v", repair_rows, REPAIR_COLUMNS, REPAIR_EMPTY_TYPES)
    return warnings


def create_empty_coherence_tables(db: DuckDB) -> None:
    db.execute(create_table_from_rows_sql(
        "coherence_v",
        [],
        COHERENCE_COLUMNS,
        COHERENCE_EMPTY_TYPES,
    ))
    validate_relation_columns(db, "coherence_v")
    db.execute(create_table_from_rows_sql(
        "coherence_repairs_v",
        [],
        REPAIR_COLUMNS,
        REPAIR_EMPTY_TYPES,
    ))
    validate_relation_columns(db, "coherence_repairs_v")


def _collect_constraints(db: DuckDB, model: EventModel) -> list[LpConstraint]:
    return _collect_constraints_from_inputs(_collect_coherence_inputs(db), model)


def _collect_coherence_inputs(db: DuckDB) -> CoherenceInputs:
    event_nodes: dict[str, list[str]] = defaultdict(list)
    current_prices: dict[str, float] = {}
    market_rows: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    family_nodes: dict[str, list[str]] = defaultdict(list)

    for row in db.rows("""
        SELECT
            event_slug,
            market_id,
            node_id,
            outcome_index,
            current_price,
            is_single_winner_family,
            outcome_label
        FROM nodes_v
        WHERE event_slug IS NOT NULL
        ORDER BY event_slug, node_id
    """):
        event_slug = str(row["event_slug"])
        node_id = str(row["node_id"])
        event_nodes[event_slug].append(node_id)
        current_prices[node_id] = float(row["current_price"] or 0.0)
        market_rows[(event_slug, str(row["market_id"]))].append((int(row["outcome_index"]), node_id))
        if row["is_single_winner_family"] and row["outcome_label"] == "Yes":
            family_nodes[event_slug].append(node_id)

    market_nodes: dict[str, list[list[str]]] = defaultdict(list)
    for (event_slug, _market_id), rows in market_rows.items():
        market_nodes[event_slug].append([node_id for _, node_id in sorted(rows)])

    logic_edges: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for row in db.rows("""
        SELECT event_slug_src, edge_type, src_node_id, dst_node_id
        FROM logic_edges_v
        WHERE event_slug_src IS NOT NULL
            AND edge_type IN ('complement', 'equivalent', 'implies', 'mutually_exclusive')
    """):
        logic_edges[(str(row["event_slug_src"]), str(row["edge_type"]))].append(
            (str(row["src_node_id"]), str(row["dst_node_id"]))
        )

    derived_implications: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for row in db.rows("""
        SELECT s.event_slug, d.src_node_id, d.dst_node_id
        FROM derived_edges_v d
        JOIN nodes_v s ON s.node_id = d.src_node_id
        WHERE s.event_slug IS NOT NULL AND d.edge_type = 'implies'
    """):
        derived_implications[str(row["event_slug"])].append(
            (str(row["src_node_id"]), str(row["dst_node_id"]))
        )

    return CoherenceInputs(
        event_nodes={slug: sorted(nodes) for slug, nodes in event_nodes.items()},
        current_prices=current_prices,
        market_nodes=dict(market_nodes),
        logic_edges=dict(logic_edges),
        derived_implications=dict(derived_implications),
        family_nodes={slug: sorted(nodes) for slug, nodes in family_nodes.items()},
    )


def _collect_constraints_from_inputs(
    inputs: CoherenceInputs,
    model: EventModel,
) -> list[LpConstraint]:
    constraints: list[LpConstraint] = []
    slug = model.event_slug

    for node_ids in inputs.market_nodes.get(slug, []):
        ids = [n for n in node_ids if n in model.index]
        if len(ids) < 2:
            continue
        coeffs = [(model.index[n], 1.0) for n in ids]
        constraints.append(LpConstraint("simplex", "eq", coeffs, 1.0))

    for src, dst in inputs.logic_edges.get((slug, "complement"), []):
        if src in model.index and dst in model.index:
            i, j = model.index[src], model.index[dst]
            constraints.append(LpConstraint("complement", "eq", [(i, 1.0), (j, 1.0)], 1.0))

    for src, dst in inputs.logic_edges.get((slug, "equivalent"), []):
        if src in model.index and dst in model.index:
            i, j = model.index[src], model.index[dst]
            constraints.append(LpConstraint("equivalent", "eq", [(i, 1.0), (j, -1.0)], 0.0))

    for src, dst in (
        inputs.logic_edges.get((slug, "implies"), [])
        + inputs.derived_implications.get(slug, [])
    ):
        if src in model.index and dst in model.index:
            i, j = model.index[src], model.index[dst]
            constraints.append(LpConstraint("implies", "le", [(i, 1.0), (j, -1.0)], 0.0))

    for src, dst in inputs.logic_edges.get((slug, "mutually_exclusive"), []):
        if src in model.index and dst in model.index:
            i, j = model.index[src], model.index[dst]
            constraints.append(LpConstraint("exclusion", "le", [(i, 1.0), (j, 1.0)], 1.0))

    coeffs = [(model.index[n], 1.0) for n in inputs.family_nodes.get(slug, []) if n in model.index]
    if len(coeffs) >= 2:
        constraints.append(LpConstraint("family_sum", "le", coeffs, 1.0))
    return constraints


def _constraints_satisfied(
    model: EventModel,
    constraints: list[LpConstraint],
    *,
    tolerance: float = 1e-9,
) -> bool:
    for constraint in constraints:
        lhs = sum(model.observed[idx] * weight for idx, weight in constraint.coeffs)
        if constraint.sense == "eq" and abs(lhs - constraint.rhs) > tolerance:
            return False
        if constraint.sense == "le" and lhs > constraint.rhs + tolerance:
            return False
    return True


def _solve_l1_repair(
    model: EventModel,
    constraints: list[LpConstraint],
) -> tuple[np.ndarray, float, str]:
    n = len(model.node_ids)
    if n == 0:
        return model.observed.copy(), 0.0, "empty"
    # Variables: x (n), s_plus (n), s_minus (n)
    num_vars = 3 * n
    c = np.zeros(num_vars)
    c[n:2 * n] = 1.0
    c[2 * n:] = 1.0

    eq_rows: list[int] = []
    eq_cols: list[int] = []
    eq_data: list[float] = []
    b_eq = []
    for i in range(n):
        row_idx = len(b_eq)
        eq_rows.extend([row_idx, row_idx, row_idx])
        eq_cols.extend([i, n + i, 2 * n + i])
        eq_data.extend([1.0, -1.0, 1.0])
        b_eq.append(model.observed[i])
    ub_rows: list[int] = []
    ub_cols: list[int] = []
    ub_data: list[float] = []
    b_ub = []
    for constraint in constraints:
        if constraint.sense == "le":
            row_idx = len(b_ub)
            for idx, weight in constraint.coeffs:
                ub_rows.append(row_idx)
                ub_cols.append(idx)
                ub_data.append(weight)
            b_ub.append(constraint.rhs)
        elif constraint.sense == "eq":
            row_idx = len(b_eq)
            for idx, weight in constraint.coeffs:
                eq_rows.append(row_idx)
                eq_cols.append(idx)
                eq_data.append(weight)
            b_eq.append(constraint.rhs)
        else:
            raise ValueError(f"Unsupported LP constraint sense: {constraint.sense}")

    A_eq_arr = csr_matrix((eq_data, (eq_rows, eq_cols)), shape=(len(b_eq), num_vars)) if b_eq else None
    A_ub_arr = csr_matrix((ub_data, (ub_rows, ub_cols)), shape=(len(b_ub), num_vars)) if b_ub else None
    b_eq_arr = np.array(b_eq) if b_eq else None

    bounds = [(0.0, 1.0)] * n + [(0.0, None)] * (2 * n)
    result = linprog(
        c,
        A_ub=A_ub_arr,
        b_ub=np.array(b_ub) if b_ub else None,
        A_eq=A_eq_arr,
        b_eq=b_eq_arr,
        bounds=bounds,
        method="highs",
    )
    if not result.success:
        return model.observed.copy(), float("inf"), result.message
    x = result.x[:n]
    distance = float(np.sum(np.abs(x - model.observed)))
    return x, distance, "optimal"


def _derived_values_sql(rows: list[dict[str, Any]]) -> str:
    return (
        "SELECT * FROM (VALUES "
        + values_rows_sql(rows, DERIVED_EDGE_COLUMNS)
        + f") AS t({', '.join(DERIVED_EDGE_COLUMNS)})"
    )


def _write_table(
    db: DuckDB,
    path: Path,
    table: str,
    rows: list[dict[str, Any]],
    columns: list[str],
    empty_types: dict[str, str],
) -> None:
    db.execute(create_table_from_rows_sql(table, rows, columns, empty_types))
    validate_relation_columns(db, table, columns)
    projection = ", ".join(columns)
    db.execute(
        f"""
        COPY (
            SELECT {projection}
            FROM {table}
        ) TO '{q(path)}' (FORMAT PARQUET);
        """
    )
