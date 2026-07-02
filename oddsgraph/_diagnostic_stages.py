from __future__ import annotations

from pathlib import Path
from typing import Any

from . import thresholds as T
from .artifacts import artifact_projection
from .contracts import validate_relation_columns
from .queries import DuckDB, q


def write_constraints(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        """
        CREATE TABLE constraint_hyperedges_v AS
            WITH pair_nodes AS (
                SELECT
                    market_id,
                    any_value(event_slug) AS event_slug,
                    any_value(question) AS question,
                    any_value(expected_tokens) AS expected_tokens,
                    list(node_id ORDER BY outcome_index) AS node_ids
                FROM nodes_v
                GROUP BY market_id
            ),
            market_sums AS (
                SELECT market_id, avg(scoring_price_sum) AS mean_sum_price
                FROM market_minute_sums
                WHERE is_complete
                GROUP BY market_id
            ),
            current_sums AS (
                SELECT market_id, scoring_price_sum AS current_sum_price
                FROM market_minute_sums
                WHERE is_current_complete
            )
            SELECT
                'market:' || p.market_id AS constraint_id,
                CASE WHEN p.expected_tokens = 2 THEN 'complement_pair' ELSE 'one_of_n' END AS constraint_type,
                p.market_id,
                p.event_slug,
                p.question,
                p.node_ids,
                c.current_sum_price,
                m.mean_sum_price,
                '1' AS expected_sum_price,
                abs(coalesce(m.mean_sum_price, 0) - 1) AS violation_score,
                CASE
                    WHEN m.mean_sum_price IS NULL THEN 0
                    ELSE greatest(0, 1 - 20 * abs(m.mean_sum_price - 1))
                END AS confidence,
                CASE
                    WHEN p.expected_tokens = 2 THEN 'binary market tokens should sum to 1'
                    ELSE 'n-ary market tokens should sum to 1'
                END AS evidence
            FROM pair_nodes p
            LEFT JOIN market_sums m USING (market_id)
            LEFT JOIN current_sums c USING (market_id);
        """
    )
    validate_relation_columns(db, "constraint_hyperedges_v")
    db.execute(
        f"""
        COPY (
            SELECT {artifact_projection("constraint_hyperedges.parquet")}
            FROM constraint_hyperedges_v
        ) TO '{q(out_dir / "constraint_hyperedges.parquet")}' (FORMAT PARQUET);
        """
    )


def write_conditionals(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        CREATE TABLE conditional_edges_v AS
        WITH repaired AS (
            SELECT node_id, coalesce(repaired_price, observed_price) AS price
            FROM coherence_repairs_v
        ),
        pair_prices AS (
            SELECT
                c.src_node_id,
                c.dst_node_id,
                coalesce(rs.price, p.current_p_src) AS current_p_src,
                coalesce(rd.price, p.current_p_dst) AS current_p_dst
            FROM (SELECT DISTINCT src_node_id, dst_node_id FROM candidate_edges_v) c
            JOIN current_pair_prices p USING (src_node_id, dst_node_id)
            LEFT JOIN repaired rs ON rs.node_id = c.src_node_id
            LEFT JOIN repaired rd ON rd.node_id = c.dst_node_id
        ),
        all_logic AS (
            SELECT src_node_id, dst_node_id, edge_type, edge_basis, confidence, evidence, current_p_src, current_p_dst
            FROM logic_edges_v
            UNION ALL
            SELECT d.src_node_id, d.dst_node_id, d.edge_type, d.edge_basis, d.confidence, d.evidence,
                p.current_p_src, p.current_p_dst
            FROM derived_edges_v d
            JOIN current_pair_prices p
                ON p.src_node_id = d.src_node_id AND p.dst_node_id = d.dst_node_id
        ),
        exact_forward AS (
            SELECT
                src_node_id AS a_node_id,
                dst_node_id AS b_node_id,
                CASE
                    WHEN edge_type IN ('complement', 'mutually_exclusive') THEN 0.0
                    WHEN edge_type = 'implies' AND current_p_dst > 0
                        THEN least(1.0, current_p_src / current_p_dst)
                    WHEN edge_type = 'equivalent' THEN 1.0
                    ELSE NULL
                END AS p_a_given_b,
                CASE
                    WHEN edge_type IN ('complement', 'mutually_exclusive') THEN 0.0
                    WHEN edge_type = 'implies' AND current_p_dst > 0
                        THEN least(1.0, current_p_src / current_p_dst)
                    WHEN edge_type = 'equivalent' THEN 1.0
                    ELSE NULL
                END AS lower_bound,
                CASE
                    WHEN edge_type IN ('complement', 'mutually_exclusive') THEN 0.0
                    WHEN edge_type = 'implies' AND current_p_dst > 0
                        THEN least(1.0, current_p_src / current_p_dst)
                    WHEN edge_type = 'equivalent' THEN 1.0
                    ELSE NULL
                END AS upper_bound,
                CASE
                    WHEN edge_type = 'complement' THEN 'exact_complement'
                    WHEN edge_type = 'mutually_exclusive' THEN 'exact_exclusion'
                    WHEN edge_type = 'implies' THEN 'exact_implication_reverse'
                    WHEN edge_type = 'equivalent' THEN 'exact_equivalence'
                    ELSE 'unknown'
                END AS method,
                confidence,
                NULL::TIMESTAMP WITH TIME ZONE AS as_of_ts,
                evidence
            FROM all_logic
            WHERE edge_type IN ('complement', 'mutually_exclusive', 'implies', 'equivalent')
        ),
        exact_symmetric AS (
            SELECT
                dst_node_id AS a_node_id,
                src_node_id AS b_node_id,
                CASE WHEN edge_type = 'equivalent' THEN 1.0 ELSE 0.0 END AS p_a_given_b,
                CASE WHEN edge_type = 'equivalent' THEN 1.0 ELSE 0.0 END AS lower_bound,
                CASE WHEN edge_type = 'equivalent' THEN 1.0 ELSE 0.0 END AS upper_bound,
                CASE
                    WHEN edge_type = 'complement' THEN 'exact_complement'
                    WHEN edge_type = 'mutually_exclusive' THEN 'exact_exclusion'
                    ELSE 'exact_equivalence'
                END AS method,
                confidence,
                NULL::TIMESTAMP WITH TIME ZONE AS as_of_ts,
                evidence
            FROM all_logic
            WHERE edge_type IN ('complement', 'mutually_exclusive', 'equivalent')
        ),
        exact_implication AS (
            SELECT
                dst_node_id,
                src_node_id,
                1.0,
                1.0,
                1.0,
                'exact_implication',
                confidence,
                NULL::TIMESTAMP WITH TIME ZONE,
                evidence
            FROM all_logic
            WHERE edge_type = 'implies'
        ),
        exact_rows AS (
            SELECT * FROM exact_forward
            UNION ALL SELECT * FROM exact_symmetric
            UNION ALL SELECT * FROM exact_implication
        ),
        frechet AS (
            SELECT
                c.src_node_id AS a_node_id,
                c.dst_node_id AS b_node_id,
                NULL::DOUBLE AS p_a_given_b,
                CASE WHEN p.current_p_dst > 0 THEN greatest(0, p.current_p_src + p.current_p_dst - 1) / p.current_p_dst END AS lower_bound,
                CASE WHEN p.current_p_dst > 0 THEN least(p.current_p_src, p.current_p_dst) / p.current_p_dst END AS upper_bound,
                'bounded_frechet' AS method,
                0.1 AS confidence,
                NULL::TIMESTAMP WITH TIME ZONE AS as_of_ts,
                'candidate-related pair without accepted exact relation' AS evidence
            FROM (SELECT DISTINCT src_node_id, dst_node_id FROM candidate_edges_v) c
            JOIN pair_prices p USING (src_node_id, dst_node_id)
            LEFT JOIN all_logic e
                ON e.src_node_id = c.src_node_id AND e.dst_node_id = c.dst_node_id
            WHERE e.src_node_id IS NULL
        )
        SELECT * FROM exact_rows
        UNION ALL
        SELECT * FROM frechet;

        """
    )
    validate_relation_columns(db, "conditional_edges_v")
    db.execute(
        f"""
        COPY (
            SELECT {artifact_projection("conditional_edges.parquet")}
            FROM conditional_edges_v
        ) TO '{q(out_dir / "conditional_edges.parquet")}' (FORMAT PARQUET);
        """
    )


def write_violations(db: DuckDB, out_dir: Path, effective: Any) -> None:
    comp_current = effective.complement_current_gap_violation_min
    comp_mean = effective.complement_mean_gap_violation_min
    eq_current = effective.equivalence_current_abs_diff_max
    imp_slack = effective.implication_current_slack
    excl_sum = effective.exclusion_current_sum_max
    db.execute(
        f"""
        CREATE TABLE violations_v AS
        WITH pair_gaps AS (
            SELECT
                c.src_node_id,
                c.dst_node_id,
                c.market_id_src,
                c.market_id_dst,
                c.event_slug_src,
                c.event_slug_dst,
                s.overlap_minutes,
                abs(p.current_p_src + p.current_p_dst - 1) AS current_gap,
                s.complement_error AS mean_gap,
                p.staleness_minutes,
                pers.trailing_breach_minutes,
                pers.breach_fraction_recent,
                pers.first_seen_ts,
                pers.last_seen_ts,
                'same-market tokens do not sum to 1' AS description
            FROM candidate_edges_v c
            JOIN aligned_edges s USING (src_node_id, dst_node_id, candidate_type)
            JOIN current_pair_prices p USING (src_node_id, dst_node_id)
            LEFT JOIN pair_persistence pers
                ON pers.src_node_id = c.src_node_id
                AND pers.dst_node_id = c.dst_node_id
                AND pers.candidate_type = c.candidate_type
            WHERE c.candidate_type = 'complement'
                AND pers.trailing_breach_minutes >= {T.VIOLATION_MIN_PERSISTENCE_MINUTES}
                AND (
                    abs(p.current_p_src + p.current_p_dst - 1) >= greatest(
                        {comp_current}, {T.K_SIGMA} * coalesce(s.pair_noise_floor, 0.01))
                    OR s.complement_error >= greatest({comp_mean}, {T.K_SIGMA} * coalesce(s.pair_noise_floor, 0.01))
                )
        ),
        edge_violations AS (
            SELECT
                e.edge_type,
                e.src_node_id,
                e.dst_node_id,
                e.market_id_src,
                e.market_id_dst,
                e.event_slug_src,
                e.event_slug_dst,
                CASE
                    WHEN e.edge_type = 'equivalent' THEN abs(e.current_p_src - e.current_p_dst)
                    WHEN e.edge_type = 'implies' THEN greatest(0, e.current_p_src - e.current_p_dst)
                    WHEN e.edge_type = 'mutually_exclusive' THEN greatest(0, e.current_p_src + e.current_p_dst - 1)
                    ELSE 0
                END AS current_gap,
                e.violation_score AS mean_gap,
                p.staleness_minutes,
                pers.trailing_breach_minutes,
                pers.breach_fraction_recent,
                pers.first_seen_ts,
                pers.last_seen_ts,
                e.evidence AS description
            FROM logic_edges_v e
            JOIN current_pair_prices p USING (src_node_id, dst_node_id)
            LEFT JOIN pair_persistence pers
                ON pers.src_node_id = e.src_node_id
                AND pers.dst_node_id = e.dst_node_id
                AND pers.candidate_type = CASE e.edge_type
                    WHEN 'equivalent' THEN 'equivalence'
                    WHEN 'implies' THEN 'implication'
                    WHEN 'mutually_exclusive' THEN 'mutual_exclusion'
                    ELSE 'complement'
                END
            WHERE pers.trailing_breach_minutes >= {T.VIOLATION_MIN_PERSISTENCE_MINUTES}
                AND (
                    (e.edge_type = 'equivalent' AND abs(e.current_p_src - e.current_p_dst) > {eq_current})
                    OR (e.edge_type = 'implies' AND e.current_p_src > e.current_p_dst + {imp_slack})
                    OR (e.edge_type = 'mutually_exclusive' AND e.current_p_src + e.current_p_dst > {excl_sum})
                )
        ),
        global_incoherence AS (
            SELECT
                'global:' || event_slug AS violation_id,
                'global_incoherence' AS violation_type,
                NULL::VARCHAR AS src_node_id,
                NULL::VARCHAR AS dst_node_id,
                NULL::VARCHAR AS market_id_src,
                NULL::VARCHAR AS market_id_dst,
                event_slug AS event_slug_src,
                event_slug AS event_slug_dst,
                CASE WHEN incoherence_distance >= {T.LP_INCOHERENCE_THRESHOLD * 2} THEN 'high' ELSE 'medium' END AS severity,
                incoherence_distance AS current_gap,
                incoherence_distance AS mean_gap,
                0.0 AS staleness_minutes,
                NULL::BIGINT AS trailing_breach_minutes,
                NULL::DOUBLE AS breach_fraction_recent,
                NULL::TIMESTAMP WITH TIME ZONE AS first_seen_ts,
                NULL::TIMESTAMP WITH TIME ZONE AS last_seen_ts,
                'event-level LP repair distance exceeds threshold' AS description
            FROM coherence_v
            WHERE incoherence_distance >= {T.LP_INCOHERENCE_THRESHOLD}
        )
        SELECT
            'complement:' || src_node_id || ':' || dst_node_id AS violation_id,
            'complement_violation' AS violation_type,
            src_node_id,
            dst_node_id,
            market_id_src,
            market_id_dst,
            event_slug_src,
            event_slug_dst,
            CASE
                WHEN staleness_minutes > {T.MAX_CURRENT_SKEW_MINUTES} THEN 'low'
                WHEN current_gap >= 0.05 OR mean_gap >= 0.025 THEN 'high'
                ELSE 'medium'
            END AS severity,
            current_gap,
            mean_gap,
            coalesce(breach_fraction_recent, 0.0) AS confidence,
            first_seen_ts,
            last_seen_ts,
            description
        FROM pair_gaps
        UNION ALL
        SELECT
            edge_type || ':' || src_node_id || ':' || dst_node_id,
            CASE
                WHEN edge_type = 'equivalent' THEN 'equivalence_divergence'
                WHEN edge_type = 'implies' THEN 'implication_violation'
                WHEN edge_type = 'mutually_exclusive' THEN 'mutual_exclusion_violation'
                ELSE 'market_sum_violation'
            END,
            src_node_id,
            dst_node_id,
            market_id_src,
            market_id_dst,
            event_slug_src,
            event_slug_dst,
            CASE
                WHEN staleness_minutes > {T.MAX_CURRENT_SKEW_MINUTES} THEN 'low'
                WHEN current_gap >= 0.05 THEN 'high'
                ELSE 'medium'
            END,
            current_gap,
            mean_gap,
            coalesce(breach_fraction_recent, 0.0),
            first_seen_ts,
            last_seen_ts,
            description
        FROM edge_violations
        UNION ALL
        SELECT
            violation_id,
            violation_type,
            src_node_id,
            dst_node_id,
            market_id_src,
            market_id_dst,
            event_slug_src,
            event_slug_dst,
            severity,
            current_gap,
            mean_gap,
            least(1.0, current_gap / {T.LP_INCOHERENCE_THRESHOLD}) AS confidence,
            first_seen_ts,
            last_seen_ts,
            description
        FROM global_incoherence;
        """
    )
    validate_relation_columns(db, "violations_v")
    db.execute(
        f"""
        COPY (
            SELECT {artifact_projection("violations.parquet")}
            FROM violations_v
        ) TO '{q(out_dir / "violations.parquet")}' (FORMAT PARQUET);
        """
    )
