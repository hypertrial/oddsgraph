from __future__ import annotations


PARQUET_ARTIFACTS = (
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
)

OPTIONAL_PARQUET_ARTIFACTS = ("evaluation.parquet",)

REPORTS = (
    "summary.md",
    "top_complement_violations.md",
    "strongest_implications.md",
    "strongest_exclusions.md",
    "duplicate_candidates.md",
    "price_only_edges.md",
    "coverage.md",
    "conditional_examples.md",
    "evaluation.md",
)

FINAL_EDGE_ARTIFACT_TABLES = {
    "logic_edges.parquet": "logic_edges_v",
    "price_edges.parquet": "price_edges_v",
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
    "evaluation.parquet": [
        "metric_type", "artifact", "edge_basis", "edge_type", "violation_type",
        "liquidity_bucket", "edge_count", "value",
    ],
}


def parquet_artifacts(
    *,
    has_evaluation: bool,
    has_prices: bool = True,
    has_coherence: bool = True,
) -> tuple[str, ...]:
    artifacts = list(PARQUET_ARTIFACTS)
    if not has_prices:
        artifacts.remove("prices.parquet")
    if not has_coherence:
        artifacts.remove("coherence.parquet")
        artifacts.remove("coherence_repairs.parquet")
    if has_evaluation:
        artifacts.extend(OPTIONAL_PARQUET_ARTIFACTS)
    return tuple(artifacts)


def reports(*, has_evaluation: bool) -> tuple[str, ...]:
    if has_evaluation:
        return tuple(f"reports/{name}" for name in REPORTS)
    return tuple(f"reports/{name}" for name in REPORTS if name != "evaluation.md")
