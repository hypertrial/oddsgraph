from __future__ import annotations

from collections.abc import Sequence

from .artifacts import ARTIFACT_COLUMNS
from .queries import DuckDB


INPUT_PRICE_COLUMNS = [
    "market_id",
    "outcome_index",
    "clob_token_id",
    "question",
    "outcome_label",
    "event_slug",
    "is_active",
    "is_closed",
    "market_volume_usd",
    "odds_timestamp",
    "odds_timestamp_epoch",
    "odds_minute_epoch",
    "price",
]

ENRICHED_MINUTE_COLUMNS = [
    *INPUT_PRICE_COLUMNS,
    "market_minute_sum",
    "price_devig",
    "scoring_price",
    "noise_floor",
]

TOKEN_STATS_COLUMNS = [
    "node_id",
    "market_id",
    "outcome_index",
    "clob_token_id",
    "question",
    "outcome_label",
    "event_slug",
    "is_active",
    "is_closed",
    "market_volume_usd",
    "first_seen_ts",
    "last_seen_ts",
    "active_minutes",
    "mean_price",
    "min_price",
    "max_price",
    "mean_price_devig",
]

NODES_VIEW_COLUMNS = [
    *TOKEN_STATS_COLUMNS,
    "canonical_proposition",
    "proposition_type",
    "stage_subject",
    "stage_rank",
    "is_single_winner_family",
    "expected_tokens",
    "market_family",
    "current_price",
    "current_price_devig",
    "current_epoch",
]

ALIGNED_EDGES_COLUMNS = [
    "src_node_id",
    "dst_node_id",
    "candidate_type",
    "overlap_minutes",
    "mean_p_src",
    "mean_p_dst",
    "complement_error",
    "equivalence_error",
    "implication_violation",
    "exclusion_violation",
    "complement_error_raw",
    "equivalence_error_raw",
    "implication_violation_raw",
    "exclusion_violation_raw",
    "gap_sigma",
    "pair_noise_floor",
    "gap_recent_max",
    "pair_max_epoch",
]

CURRENT_PAIR_PRICE_COLUMNS = [
    "src_node_id",
    "dst_node_id",
    "current_p_src",
    "current_p_dst",
    "current_epoch_src",
    "current_epoch_dst",
    "staleness_minutes",
]

SCORED_EDGES_RAW_COLUMNS = [
    "src_node_id",
    "dst_node_id",
    "candidate_type",
    "edge_type",
    "edge_basis",
    "confidence",
    "score",
    "violation_score",
    "overlap_minutes",
    "current_p_src",
    "current_p_dst",
    "current_epoch_src",
    "current_epoch_dst",
    "staleness_minutes",
    "mean_p_src",
    "mean_p_dst",
    "complement_error_raw",
    "equivalence_error_raw",
    "implication_violation_raw",
    "exclusion_violation_raw",
    "gap_sigma",
    "pair_noise_floor",
    "gap_recent_max",
    "market_id_src",
    "market_id_dst",
    "event_slug_src",
    "event_slug_dst",
    "evidence",
]

SCORED_EDGES_COLUMNS = [
    "src_node_id",
    "dst_node_id",
    "candidate_type",
    *ARTIFACT_COLUMNS["logic_edges.parquet"][2:],
]

INTERNAL_TABLE_COLUMNS = {
    "input_prices": INPUT_PRICE_COLUMNS,
    "token_minute_prices": INPUT_PRICE_COLUMNS,
    "quote_minute_prices": ["clob_token_id", "odds_minute_epoch", "mid_price", "half_spread"],
    "enriched_minute_prices": ENRICHED_MINUTE_COLUMNS,
    "scoring_minute_prices": ENRICHED_MINUTE_COLUMNS,
    "market_token_counts": ["market_id", "expected_tokens"],
    "market_complete_epochs": ["market_id", "current_minute_epoch"],
    "market_minute_sums": [
        "market_id",
        "odds_minute_epoch",
        "token_count",
        "expected_tokens",
        "raw_price_sum",
        "scoring_price_sum",
        "is_complete",
        "is_current_complete",
    ],
    "token_stats": TOKEN_STATS_COLUMNS,
    "token_current": ["node_id", "current_price", "current_price_devig", "current_ts", "current_epoch"],
    "nodes_v": NODES_VIEW_COLUMNS,
    "candidate_edges_v": ARTIFACT_COLUMNS["candidate_edges.parquet"],
    "aligned_edges": ALIGNED_EDGES_COLUMNS,
    "pair_persistence": [
        "src_node_id",
        "dst_node_id",
        "candidate_type",
        "trailing_breach_minutes",
        "first_seen_ts",
        "last_seen_ts",
        "trailing_window_minutes",
        "breach_fraction_recent",
    ],
    "current_pair_prices": CURRENT_PAIR_PRICE_COLUMNS,
    "logic_edges_v": ARTIFACT_COLUMNS["logic_edges.parquet"],
    "price_edges_v": ARTIFACT_COLUMNS["price_edges.parquet"],
    "derived_edges_v": ARTIFACT_COLUMNS["derived_edges.parquet"],
    "constraint_hyperedges_v": ARTIFACT_COLUMNS["constraint_hyperedges.parquet"],
    "coherence_v": ARTIFACT_COLUMNS["coherence.parquet"],
    "coherence_repairs_v": ARTIFACT_COLUMNS["coherence_repairs.parquet"],
    "conditional_edges_v": ARTIFACT_COLUMNS["conditional_edges.parquet"],
    "violations_v": ARTIFACT_COLUMNS["violations.parquet"],
    "calibration_v": ARTIFACT_COLUMNS["calibration.parquet"],
    "evaluation_v": ARTIFACT_COLUMNS["evaluation.parquet"],
}


def validate_relation_columns(
    db: DuckDB,
    relation: str,
    expected_columns: Sequence[str] | None = None,
) -> None:
    expected = list(expected_columns or INTERNAL_TABLE_COLUMNS[relation])
    actual = [
        str(row["column_name"])
        for row in db.rows(f"DESCRIBE SELECT * FROM {relation}")
    ]
    if actual != expected:
        raise RuntimeError(f"{relation} column contract drift: expected {expected}, got {actual}")
