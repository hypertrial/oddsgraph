from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from . import noise
from . import thresholds as T
from .artifacts import artifact_projection
from .contracts import SCORED_EDGES_RAW_COLUMNS, validate_relation_columns
from .queries import DuckDB, q

T_ = TypeVar("T_")


def write_candidates(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        CREATE TABLE candidate_edges_v AS
        WITH same_market_binary AS (
            SELECT
                a.node_id AS src_node_id,
                b.node_id AS dst_node_id,
                'complement' AS candidate_type,
                'same_market' AS candidate_source,
                1.0 AS candidate_score,
                a.market_id AS market_id_src,
                b.market_id AS market_id_dst,
                a.event_slug AS event_slug_src,
                b.event_slug AS event_slug_dst
            FROM nodes_v a
            JOIN nodes_v b
                ON a.market_id = b.market_id
                AND a.outcome_index < b.outcome_index
            WHERE a.expected_tokens = 2
        ),
        same_market_nary AS (
            SELECT
                a.node_id AS src_node_id,
                b.node_id AS dst_node_id,
                'mutual_exclusion' AS candidate_type,
                'same_market' AS candidate_source,
                1.0 AS candidate_score,
                a.market_id AS market_id_src,
                b.market_id AS market_id_dst,
                a.event_slug AS event_slug_src,
                b.event_slug AS event_slug_dst
            FROM nodes_v a
            JOIN nodes_v b
                ON a.market_id = b.market_id
                AND a.outcome_index < b.outcome_index
            WHERE a.expected_tokens > 2
        ),
        eligible AS (
            SELECT *
            FROM nodes_v
            WHERE market_volume_usd >= {T.MIN_MARKET_VOLUME_USD}
                AND active_minutes >= {T.MIN_ACTIVE_MINUTES}
                AND outcome_label = 'Yes'
        ),
        exact_duplicates AS (
            SELECT
                a.node_id AS src_node_id,
                b.node_id AS dst_node_id,
                'equivalence' AS candidate_type,
                'exact_duplicate_same_event' AS candidate_source,
                1.0 AS candidate_score,
                a.market_id AS market_id_src,
                b.market_id AS market_id_dst,
                a.event_slug AS event_slug_src,
                b.event_slug AS event_slug_dst
            FROM nodes_v a
            JOIN nodes_v b
                ON a.event_slug = b.event_slug
                AND a.canonical_proposition = b.canonical_proposition
                AND a.market_id < b.market_id
        ),
        single_winner AS (
            SELECT
                a.node_id AS src_node_id,
                b.node_id AS dst_node_id,
                'mutual_exclusion' AS candidate_type,
                'semantic_single_winner' AS candidate_source,
                1.0 AS candidate_score,
                a.market_id AS market_id_src,
                b.market_id AS market_id_dst,
                a.event_slug AS event_slug_src,
                b.event_slug AS event_slug_dst
            FROM nodes_v a
            JOIN nodes_v b
                ON a.event_slug = b.event_slug
                AND a.market_id < b.market_id
            WHERE a.outcome_label = 'Yes'
                AND b.outcome_label = 'Yes'
                AND a.canonical_proposition != b.canonical_proposition
                AND a.is_single_winner_family
                AND b.is_single_winner_family
        ),
        stage_progression AS (
            SELECT
                a.node_id AS src_node_id,
                b.node_id AS dst_node_id,
                'implication' AS candidate_type,
                'semantic_stage_progression' AS candidate_source,
                1.0 AS candidate_score,
                a.market_id AS market_id_src,
                b.market_id AS market_id_dst,
                a.event_slug AS event_slug_src,
                b.event_slug AS event_slug_dst
            FROM nodes_v a
            JOIN nodes_v b
                ON a.stage_subject = b.stage_subject
                AND a.stage_rank > b.stage_rank
                AND a.market_id != b.market_id
            WHERE a.outcome_label = 'Yes'
                AND b.outcome_label = 'Yes'
                AND a.stage_subject IS NOT NULL
                AND b.stage_subject IS NOT NULL
        ),
        price_cross_market AS (
            SELECT
                a.node_id AS src_node_id,
                b.node_id AS dst_node_id,
                candidate_type,
                'price_same_event_slug' AS candidate_source,
                0.5 AS candidate_score,
                a.market_id AS market_id_src,
                b.market_id AS market_id_dst,
                a.event_slug AS event_slug_src,
                b.event_slug AS event_slug_dst
            FROM eligible a
            JOIN eligible b
                ON a.event_slug = b.event_slug
                AND a.market_id < b.market_id
            CROSS JOIN (VALUES ('equivalence'), ('mutual_exclusion')) AS t(candidate_type)
            UNION ALL
            SELECT
                a.node_id,
                b.node_id,
                'implication',
                'price_same_event_slug',
                0.5,
                a.market_id,
                b.market_id,
                a.event_slug,
                b.event_slug
            FROM eligible a
            JOIN eligible b
                ON a.event_slug = b.event_slug
                AND a.market_id != b.market_id
        )
        SELECT
            src_node_id,
            dst_node_id,
            candidate_type,
            arg_max(candidate_source, candidate_score) AS candidate_source,
            max(candidate_score) AS candidate_score,
            any_value(market_id_src) AS market_id_src,
            any_value(market_id_dst) AS market_id_dst,
            any_value(event_slug_src) AS event_slug_src,
            any_value(event_slug_dst) AS event_slug_dst
        FROM (
            SELECT * FROM same_market_binary
            UNION ALL SELECT * FROM same_market_nary
            UNION ALL SELECT * FROM exact_duplicates
            UNION ALL SELECT * FROM single_winner
            UNION ALL SELECT * FROM stage_progression
            UNION ALL SELECT * FROM price_cross_market
        )
        GROUP BY 1, 2, 3;
        """
    )
    validate_relation_columns(db, "candidate_edges_v")
    db.execute(
        f"""
        COPY (
            SELECT {artifact_projection("candidate_edges.parquet")}
            FROM candidate_edges_v
        ) TO '{q(out_dir / 'candidate_edges.parquet')}' (FORMAT PARQUET);
        """
    )


def score_edges(
    db: DuckDB,
    out_dir: Path,
    stage: Callable[[str, Callable[[], T_]], T_],
    *,
    lookback_days: int | None = None,
) -> None:
    del out_dir
    def create_scoring_minute_prices() -> None:
        db.execute(noise.create_scoring_minute_prices_sql(lookback_days))
        validate_relation_columns(db, "scoring_minute_prices")

    def create_aligned_edges() -> None:
        db.execute(noise.create_aligned_edges_sql())
        validate_relation_columns(db, "aligned_edges")

    def create_pair_persistence() -> None:
        db.execute(noise.create_pair_persistence_sql())
        validate_relation_columns(db, "pair_persistence")

    stage("  scoring_minute_prices", create_scoring_minute_prices)
    stage("  aligned_edges", create_aligned_edges)
    stage("  pair_persistence", create_pair_persistence)
    db.execute(
        f"""
        CREATE TABLE current_pair_prices AS
        SELECT
            c.src_node_id,
            c.dst_node_id,
            a.current_price AS current_p_src,
            b.current_price AS current_p_dst,
            a.current_epoch AS current_epoch_src,
            b.current_epoch AS current_epoch_dst,
            abs(a.current_epoch - b.current_epoch) / 60.0 AS staleness_minutes
        FROM (SELECT DISTINCT src_node_id, dst_node_id FROM candidate_edges_v) c
        JOIN token_current a ON a.node_id = c.src_node_id
        JOIN token_current b ON b.node_id = c.dst_node_id;

        CREATE TABLE scored_edges_v AS
        SELECT
            c.src_node_id,
            c.dst_node_id,
            c.candidate_type,
            CASE
                WHEN c.candidate_type = 'complement' THEN 'complement'
                WHEN c.candidate_type = 'equivalence' THEN 'equivalent'
                WHEN c.candidate_type = 'implication' THEN 'implies'
                WHEN c.candidate_type = 'mutual_exclusion' THEN 'mutually_exclusive'
                ELSE 'related'
            END AS edge_type,
            CASE
                WHEN c.candidate_source = 'same_market' AND c.candidate_type = 'complement' THEN 'same_market'
                WHEN c.candidate_source = 'same_market' AND c.candidate_type = 'mutual_exclusion' THEN 'same_market'
                WHEN c.candidate_source = 'exact_duplicate_same_event' THEN 'exact_duplicate'
                WHEN c.candidate_source = 'semantic_single_winner' THEN 'single_winner_family'
                WHEN c.candidate_source = 'semantic_stage_progression' THEN 'stage_progression_rule'
                ELSE 'price_only'
            END AS edge_basis,
            CASE
                WHEN c.candidate_type = 'complement' AND s.overlap_minutes < {T.COMPLEMENT_LOW_OVERLAP_MINUTES} THEN 0.5
                WHEN c.candidate_type = 'complement' THEN coalesce(greatest(0, 1 - 20 * s.complement_error), 0.5)
                WHEN c.candidate_type = 'equivalence' THEN coalesce(greatest(0, 1 - 20 * s.equivalence_error), 0.5)
                WHEN c.candidate_type = 'implication' THEN coalesce(greatest(0, 1 - 50 * s.implication_violation), 0.5)
                WHEN c.candidate_type = 'mutual_exclusion' THEN coalesce(greatest(0, 1 - 50 * s.exclusion_violation), 0.5)
                ELSE 0.1
            END AS confidence,
            CASE c.candidate_type
                WHEN 'complement' THEN s.complement_error
                WHEN 'equivalence' THEN s.equivalence_error
                WHEN 'implication' THEN s.implication_violation
                WHEN 'mutual_exclusion' THEN s.exclusion_violation
                ELSE NULL
            END AS score,
            CASE c.candidate_type
                WHEN 'complement' THEN s.complement_error
                WHEN 'equivalence' THEN greatest(0, s.equivalence_error - {T.EQUIVALENCE_MEAN_ABS_DIFF_MAX})
                WHEN 'implication' THEN s.implication_violation
                WHEN 'mutual_exclusion' THEN s.exclusion_violation
                ELSE NULL
            END AS violation_score,
            s.overlap_minutes,
            p.current_p_src,
            p.current_p_dst,
            p.current_epoch_src,
            p.current_epoch_dst,
            p.staleness_minutes,
            s.mean_p_src,
            s.mean_p_dst,
            s.complement_error_raw,
            s.equivalence_error_raw,
            s.implication_violation_raw,
            s.exclusion_violation_raw,
            s.gap_sigma,
            s.pair_noise_floor,
            s.gap_recent_max,
            c.market_id_src,
            c.market_id_dst,
            c.event_slug_src,
            c.event_slug_dst,
            CASE
                WHEN c.candidate_type = 'complement' THEN 'same market tokens sum to 1'
                WHEN c.candidate_source = 'exact_duplicate_same_event' THEN 'same canonical proposition in the same event'
                WHEN c.candidate_source = 'semantic_single_winner' THEN 'single-winner family alternatives cannot both occur'
                WHEN c.candidate_source = 'semantic_stage_progression' THEN 'higher tournament stage implies lower stage'
                WHEN c.candidate_source = 'same_market' THEN 'same market n-ary outcomes are mutually exclusive'
                WHEN c.candidate_type = 'equivalence' THEN 'price-threshold only; not accepted as logic'
                WHEN c.candidate_type = 'implication' THEN 'price-threshold only; not accepted as logic'
                WHEN c.candidate_type = 'mutual_exclusion' THEN 'price-threshold only; not accepted as logic'
                ELSE 'candidate-related pair'
            END AS evidence
        FROM candidate_edges_v c
        JOIN aligned_edges s USING (src_node_id, dst_node_id, candidate_type)
        JOIN current_pair_prices p USING (src_node_id, dst_node_id);

        CREATE TABLE logic_edges_v AS
        SELECT
            src_node_id, dst_node_id, edge_type, edge_basis, confidence, score,
            violation_score, overlap_minutes, current_p_src, current_p_dst, mean_p_src,
            mean_p_dst, market_id_src, market_id_dst, event_slug_src, event_slug_dst, evidence
        FROM scored_edges_v
        WHERE edge_basis IN (
            'same_market',
            'exact_duplicate',
            'single_winner_family',
            'stage_progression_rule'
        );

        CREATE TABLE price_edges_v AS
        SELECT
            src_node_id, dst_node_id, edge_type, edge_basis, confidence, score,
            violation_score, overlap_minutes, current_p_src, current_p_dst, mean_p_src,
            mean_p_dst, market_id_src, market_id_dst, event_slug_src, event_slug_dst, evidence
        FROM scored_edges_v s
        WHERE s.edge_basis = 'price_only'
            AND (
                (
                    s.edge_type = 'equivalent'
                    AND s.overlap_minutes >= {T.MIN_OVERLAP_MINUTES}
                    AND s.score <= {T.EQUIVALENCE_MEAN_ABS_DIFF_MAX}
                    AND abs(s.current_p_src - s.current_p_dst) <= {T.EQUIVALENCE_CURRENT_ABS_DIFF_MAX}
                )
                OR (
                    s.edge_type = 'implies'
                    AND s.overlap_minutes >= {T.MIN_OVERLAP_MINUTES}
                    AND s.violation_score <= {T.IMPLICATION_VIOLATION_MEAN_MAX}
                    AND s.current_p_src <= s.current_p_dst + {T.IMPLICATION_CURRENT_SLACK}
                )
                OR (
                    s.edge_type = 'mutually_exclusive'
                    AND s.overlap_minutes >= {T.MIN_OVERLAP_MINUTES}
                    AND s.violation_score <= {T.EXCLUSION_VIOLATION_MEAN_MAX}
                    AND s.current_p_src + s.current_p_dst <= {T.EXCLUSION_CURRENT_SUM_MAX}
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM logic_edges_v l
                WHERE l.src_node_id = s.src_node_id
                    AND l.dst_node_id = s.dst_node_id
                    AND l.edge_type = s.edge_type
            );
        """
    )
    validate_relation_columns(db, "current_pair_prices")
    validate_relation_columns(db, "scored_edges_v", SCORED_EDGES_RAW_COLUMNS)
    validate_relation_columns(db, "logic_edges_v")
    validate_relation_columns(db, "price_edges_v")
