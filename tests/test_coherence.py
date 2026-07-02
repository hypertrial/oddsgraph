from __future__ import annotations

from pathlib import Path

import pytest

from oddsgraph.coherence import (
    EventModel,
    LpConstraint,
    _collect_coherence_inputs,
    _collect_constraints,
    _collect_constraints_from_inputs,
    _constraints_satisfied,
    _solve_l1_repair,
)
from oddsgraph.queries import DuckDB


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
    assert _constraints_satisfied(model, constraints)

def test_batched_lp_constraint_collection_matches_wrapper(synthetic_output: Path) -> None:
    db = DuckDB(synthetic_output / "oddsgraph.duckdb")
    try:
        inputs = _collect_coherence_inputs(db)
        node_ids = inputs.event_nodes["world-cup-winner"]
        model = EventModel(
            "world-cup-winner",
            node_ids,
            pytest.importorskip("numpy").array([inputs.current_prices[node_id] for node_id in node_ids]),
            {node_id: idx for idx, node_id in enumerate(node_ids)},
        )
        assert _collect_constraints_from_inputs(inputs, model) == _collect_constraints(db, model)
    finally:
        db.close()
