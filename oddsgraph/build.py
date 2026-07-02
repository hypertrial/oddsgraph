from __future__ import annotations

import time
from pathlib import Path

from .queries import DuckDB, q
from .reports import write_reports
from .schema import validate_input
from . import thresholds as T


def build(input_path: Path, out_dir: Path) -> dict[str, str | int | float | None]:
    start = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = out_dir / "oddsgraph.duckdb"
    if db_path.exists():
        db_path.unlink()
    db = DuckDB(db_path)
    try:
        validate_input(db, input_path)
        _create_views(db, input_path)
        _write_prices(db, out_dir)
        _write_nodes(db, out_dir)
        _write_market_groups(db, out_dir)
        _write_candidates(db, out_dir)
        _score_edges(db, out_dir)
        _write_constraints(db, out_dir)
        _write_conditionals(db, out_dir)
        _write_violations(db, out_dir)
        stats = _stats(db, start)
        write_reports(db, out_dir, stats)
        return stats
    finally:
        db.close()


def _create_views(db: DuckDB, input_path: Path) -> None:
    src = q(input_path)
    db.execute(
        f"""
        CREATE VIEW input_prices AS
        SELECT
            market_id,
            outcome_index,
            clob_token_id,
            question,
            outcome_label,
            event_slug,
            is_active,
            is_closed,
            market_volume_usd,
            ODDS_TIMESTAMP AS odds_timestamp,
            ODDS_TIMESTAMP_EPOCH AS odds_timestamp_epoch,
            price
        FROM read_parquet('{src}');

        CREATE TABLE market_complete_epochs AS
        WITH counts AS (
            SELECT
                market_id,
                odds_timestamp_epoch,
                count(DISTINCT clob_token_id) AS token_count
            FROM input_prices
            GROUP BY 1, 2
        ),
        market_tokens AS (
            SELECT market_id, count(DISTINCT clob_token_id) AS expected_tokens
            FROM input_prices
            GROUP BY 1
        )
        SELECT c.market_id, max(c.odds_timestamp_epoch) AS current_epoch
        FROM counts c
        JOIN market_tokens t USING (market_id)
        WHERE c.token_count = t.expected_tokens
        GROUP BY c.market_id;

        CREATE TABLE token_stats AS
        SELECT
            clob_token_id AS node_id,
            any_value(market_id) AS market_id,
            any_value(outcome_index) AS outcome_index,
            any_value(clob_token_id) AS clob_token_id,
            any_value(question) AS question,
            any_value(outcome_label) AS outcome_label,
            any_value(event_slug) AS event_slug,
            any_value(is_active) AS is_active,
            any_value(is_closed) AS is_closed,
            any_value(market_volume_usd) AS market_volume_usd,
            min(odds_timestamp) AS first_seen_ts,
            max(odds_timestamp) AS last_seen_ts,
            count(DISTINCT odds_timestamp_epoch) AS active_minutes,
            avg(price) AS mean_price,
            min(price) AS min_price,
            max(price) AS max_price
        FROM input_prices
        GROUP BY clob_token_id;

        CREATE TABLE token_current AS
        SELECT
            t.node_id,
            any_value(p.price) AS current_price,
            any_value(p.odds_timestamp) AS current_ts,
            any_value(p.odds_timestamp_epoch) AS current_epoch
        FROM (
            SELECT DISTINCT clob_token_id AS node_id, market_id
            FROM input_prices
        ) t
        LEFT JOIN market_complete_epochs e ON t.market_id = e.market_id
        LEFT JOIN input_prices p
            ON p.market_id = t.market_id
            AND p.clob_token_id = t.node_id
            AND p.odds_timestamp_epoch = e.current_epoch
        GROUP BY t.node_id;

        CREATE VIEW nodes_v AS
        SELECT
            s.*,
            CASE
                WHEN s.outcome_label = 'Yes' THEN s.question
                WHEN s.outcome_label = 'No' THEN 'NOT(' || s.question || ')'
                ELSE s.question || ' :: ' || s.outcome_label
            END AS canonical_proposition,
            CASE
                WHEN s.outcome_label IN ('Yes', 'No') THEN 'binary'
                ELSE 'named_binary'
            END AS proposition_type,
            c.current_price
        FROM token_stats s
        LEFT JOIN token_current c USING (node_id);
        """
    )


def _write_prices(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        COPY (
            SELECT
                clob_token_id AS node_id,
                market_id,
                odds_timestamp,
                odds_timestamp_epoch,
                price,
                is_active,
                is_closed,
                market_volume_usd,
                ln(least(greatest(price, 0.0005), 0.9995) / (1 - least(greatest(price, 0.0005), 0.9995))) AS logit_price,
                price - lag(price) OVER (PARTITION BY clob_token_id ORDER BY odds_timestamp_epoch) AS price_return_1m
            FROM input_prices
        ) TO '{q(out_dir / "prices.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_nodes(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        COPY (
            SELECT
                node_id,
                market_id,
                outcome_index,
                clob_token_id,
                question,
                outcome_label,
                event_slug,
                is_active,
                is_closed,
                market_volume_usd,
                canonical_proposition,
                proposition_type,
                first_seen_ts,
                last_seen_ts,
                active_minutes,
                current_price,
                mean_price,
                min_price,
                max_price
            FROM nodes_v
        ) TO '{q(out_dir / "nodes.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_market_groups(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        COPY (
            WITH sums AS (
                SELECT p.market_id, p.odds_timestamp_epoch, sum(p.price) AS sum_price
                FROM input_prices p
                GROUP BY 1, 2
                HAVING count(DISTINCT p.clob_token_id) = 2
            ),
            current_sums AS (
                SELECT s.market_id, s.sum_price AS current_sum_price
                FROM sums s
                JOIN market_complete_epochs e
                    ON s.market_id = e.market_id
                    AND s.odds_timestamp_epoch = e.current_epoch
            )
            SELECT
                n.market_id,
                any_value(n.event_slug) AS event_slug,
                any_value(n.question) AS question,
                count(*) AS num_tokens,
                list(n.node_id ORDER BY n.outcome_index) AS token_ids,
                list(n.outcome_label ORDER BY n.outcome_index) AS outcome_labels,
                bool_or(n.is_active) AS is_active,
                bool_or(n.is_closed) AS is_closed,
                max(n.market_volume_usd) AS market_volume_usd,
                min(n.first_seen_ts) AS first_seen_ts,
                max(n.last_seen_ts) AS last_seen_ts,
                any_value(c.current_sum_price) AS current_sum_price,
                avg(s.sum_price) AS mean_sum_price
            FROM nodes_v n
            LEFT JOIN sums s USING (market_id)
            LEFT JOIN current_sums c USING (market_id)
            GROUP BY n.market_id
        ) TO '{q(out_dir / "market_groups.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_candidates(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        CREATE TABLE candidate_edges_v AS
        WITH same_market AS (
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
        ),
        eligible AS (
            SELECT *
            FROM nodes_v
            WHERE market_volume_usd >= {T.MIN_MARKET_VOLUME_USD}
                AND active_minutes >= {T.MIN_ACTIVE_MINUTES}
                AND outcome_label = 'Yes'
        ),
        cross_market AS (
            SELECT
                a.node_id AS src_node_id,
                b.node_id AS dst_node_id,
                candidate_type,
                'same_event_slug' AS candidate_source,
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
                'same_event_slug',
                0.5,
                a.market_id,
                b.market_id,
                a.event_slug,
                b.event_slug
            FROM eligible a
            JOIN eligible b
                ON a.event_slug = b.event_slug
                AND a.market_id != b.market_id
        ),
        duplicate_questions AS (
            SELECT
                a.node_id AS src_node_id,
                b.node_id AS dst_node_id,
                'equivalence' AS candidate_type,
                'same_question_text_exact' AS candidate_source,
                0.9 AS candidate_score,
                a.market_id AS market_id_src,
                b.market_id AS market_id_dst,
                a.event_slug AS event_slug_src,
                b.event_slug AS event_slug_dst
            FROM nodes_v a
            JOIN nodes_v b
                ON a.question = b.question
                AND a.outcome_label = b.outcome_label
                AND a.market_id < b.market_id
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
            SELECT * FROM same_market
            UNION ALL SELECT * FROM cross_market
            UNION ALL SELECT * FROM duplicate_questions
        )
        GROUP BY 1, 2, 3;
        """
    )
    db.execute(f"COPY candidate_edges_v TO '{q(out_dir / 'candidate_edges.parquet')}' (FORMAT PARQUET);")


def _score_edges(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        CREATE TABLE aligned_edges AS
        WITH pairs AS (
            SELECT DISTINCT src_node_id, dst_node_id
            FROM candidate_edges_v
        ),
        aligned AS (
            SELECT
                p.src_node_id,
                p.dst_node_id,
                a.odds_timestamp_epoch,
                a.price AS p_src,
                b.price AS p_dst
            FROM pairs p
            JOIN input_prices a ON a.clob_token_id = p.src_node_id
            JOIN input_prices b
                ON b.clob_token_id = p.dst_node_id
                AND b.odds_timestamp_epoch = a.odds_timestamp_epoch
        ),
        stats AS (
            SELECT
                src_node_id,
                dst_node_id,
                count(*) AS overlap_minutes,
                avg(p_src) AS mean_p_src,
                avg(p_dst) AS mean_p_dst,
                avg(abs(p_src + p_dst - 1)) AS complement_error,
                avg(abs(p_src - p_dst)) AS equivalence_error,
                avg(greatest(0, p_src - p_dst - {T.IMPLICATION_EPSILON})) AS implication_violation,
                avg(greatest(0, p_src + p_dst - 1 - {T.EXCLUSION_EPSILON})) AS exclusion_violation
            FROM aligned
            GROUP BY 1, 2
        )
        SELECT
            p.src_node_id,
            p.dst_node_id,
            coalesce(s.overlap_minutes, 0) AS overlap_minutes,
            s.mean_p_src,
            s.mean_p_dst,
            s.complement_error,
            s.equivalence_error,
            s.implication_violation,
            s.exclusion_violation
        FROM pairs p
        LEFT JOIN stats s USING (src_node_id, dst_node_id);

        CREATE TABLE current_pair_prices AS
        SELECT
            c.src_node_id,
            c.dst_node_id,
            a.current_price AS current_p_src,
            b.current_price AS current_p_dst
        FROM (SELECT DISTINCT src_node_id, dst_node_id FROM candidate_edges_v) c
        JOIN token_current a ON a.node_id = c.src_node_id
        JOIN token_current b ON b.node_id = c.dst_node_id;

        CREATE TABLE logic_edges_v AS
        SELECT
            c.src_node_id,
            c.dst_node_id,
            CASE
                WHEN c.candidate_type = 'complement' THEN 'complement'
                WHEN c.candidate_type = 'equivalence' THEN 'equivalent'
                WHEN c.candidate_type = 'implication' THEN 'implies'
                WHEN c.candidate_type = 'mutual_exclusion' THEN 'mutually_exclusive'
                ELSE 'related'
            END AS edge_type,
            CASE
                WHEN c.candidate_type = 'complement' AND s.overlap_minutes < {T.COMPLEMENT_LOW_OVERLAP_MINUTES} THEN 0.5
                WHEN c.candidate_type = 'complement' THEN coalesce(greatest(0, 1 - 20 * s.complement_error), 0.5)
                WHEN c.candidate_type = 'equivalence' THEN greatest(0, 1 - 20 * s.equivalence_error)
                WHEN c.candidate_type = 'implication' THEN greatest(0, 1 - 50 * s.implication_violation)
                WHEN c.candidate_type = 'mutual_exclusion' THEN greatest(0, 1 - 50 * s.exclusion_violation)
                ELSE 0.1
            END AS confidence,
            CASE
                WHEN c.candidate_type = 'complement' THEN s.complement_error
                WHEN c.candidate_type = 'equivalence' THEN s.equivalence_error
                WHEN c.candidate_type = 'implication' THEN s.implication_violation
                WHEN c.candidate_type = 'mutual_exclusion' THEN s.exclusion_violation
                ELSE NULL
            END AS score,
            CASE
                WHEN c.candidate_type = 'complement' THEN s.complement_error
                WHEN c.candidate_type = 'equivalence' THEN greatest(0, s.equivalence_error - {T.EQUIVALENCE_MEAN_ABS_DIFF_MAX})
                WHEN c.candidate_type = 'implication' THEN s.implication_violation
                WHEN c.candidate_type = 'mutual_exclusion' THEN s.exclusion_violation
                ELSE NULL
            END AS violation_score,
            s.overlap_minutes,
            p.current_p_src,
            p.current_p_dst,
            s.mean_p_src,
            s.mean_p_dst,
            c.market_id_src,
            c.market_id_dst,
            c.event_slug_src,
            c.event_slug_dst,
            CASE
                WHEN c.candidate_type = 'complement' THEN 'same market tokens sum to 1'
                WHEN c.candidate_type = 'equivalence' THEN 'prices remain close across overlapping minutes'
                WHEN c.candidate_type = 'implication' THEN 'source price rarely exceeds destination price'
                WHEN c.candidate_type = 'mutual_exclusion' THEN 'pair sum rarely exceeds 1'
                ELSE 'candidate-related pair'
            END AS evidence
        FROM candidate_edges_v c
        JOIN aligned_edges s USING (src_node_id, dst_node_id)
        JOIN current_pair_prices p USING (src_node_id, dst_node_id)
        WHERE
            (c.candidate_type = 'complement')
            OR (
                c.candidate_type = 'equivalence'
                AND s.overlap_minutes >= {T.MIN_OVERLAP_MINUTES}
                AND s.equivalence_error <= {T.EQUIVALENCE_MEAN_ABS_DIFF_MAX}
                AND abs(p.current_p_src - p.current_p_dst) <= {T.EQUIVALENCE_CURRENT_ABS_DIFF_MAX}
            )
            OR (
                c.candidate_type = 'implication'
                AND s.overlap_minutes >= {T.MIN_OVERLAP_MINUTES}
                AND s.implication_violation <= {T.IMPLICATION_VIOLATION_MEAN_MAX}
                AND p.current_p_src <= p.current_p_dst + {T.IMPLICATION_CURRENT_SLACK}
            )
            OR (
                c.candidate_type = 'mutual_exclusion'
                AND s.overlap_minutes >= {T.MIN_OVERLAP_MINUTES}
                AND s.exclusion_violation <= {T.EXCLUSION_VIOLATION_MEAN_MAX}
                AND p.current_p_src + p.current_p_dst <= {T.EXCLUSION_CURRENT_SUM_MAX}
            );
        """
    )
    db.execute(f"COPY logic_edges_v TO '{q(out_dir / 'logic_edges.parquet')}' (FORMAT PARQUET);")


def _write_constraints(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        COPY (
            WITH pair_nodes AS (
                SELECT
                    market_id,
                    any_value(event_slug) AS event_slug,
                    any_value(question) AS question,
                    list(node_id ORDER BY outcome_index) AS node_ids
                FROM nodes_v
                GROUP BY market_id
            ),
            market_sums AS (
                SELECT market_id, avg(sum_price) AS mean_sum_price
                FROM (
                    SELECT market_id, odds_timestamp_epoch, sum(price) AS sum_price
                    FROM input_prices
                    GROUP BY 1, 2
                    HAVING count(DISTINCT clob_token_id) = 2
                )
                GROUP BY market_id
            ),
            current_sums AS (
                SELECT p.market_id, sum(p.price) AS current_sum_price
                FROM input_prices p
                JOIN market_complete_epochs e
                    ON p.market_id = e.market_id
                    AND p.odds_timestamp_epoch = e.current_epoch
                GROUP BY p.market_id
            )
            SELECT
                'market:' || p.market_id AS constraint_id,
                'complement_pair' AS constraint_type,
                p.market_id,
                p.event_slug,
                p.question,
                p.node_ids,
                c.current_sum_price,
                m.mean_sum_price,
                '1' AS expected_sum_price,
                abs(m.mean_sum_price - 1) AS violation_score,
                CASE
                    WHEN m.mean_sum_price IS NULL THEN 0
                    ELSE greatest(0, 1 - 20 * abs(m.mean_sum_price - 1))
                END AS confidence,
                'binary market tokens should sum to 1' AS evidence
            FROM pair_nodes p
            LEFT JOIN market_sums m USING (market_id)
            LEFT JOIN current_sums c USING (market_id)
        ) TO '{q(out_dir / "constraint_hyperedges.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_conditionals(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        CREATE TABLE conditional_edges_v AS
        WITH exact_forward AS (
            SELECT
                src_node_id AS a_node_id,
                dst_node_id AS b_node_id,
                CASE
                    WHEN edge_type IN ('complement', 'mutually_exclusive') THEN 0.0
                    WHEN edge_type = 'implies' AND current_p_dst > 0 THEN current_p_src / current_p_dst
                    WHEN edge_type = 'equivalent' THEN 1.0
                    ELSE NULL
                END AS p_a_given_b,
                CASE
                    WHEN edge_type IN ('complement', 'mutually_exclusive') THEN 0.0
                    WHEN edge_type = 'implies' AND current_p_dst > 0 THEN current_p_src / current_p_dst
                    WHEN edge_type = 'equivalent' THEN 1.0
                    ELSE NULL
                END AS lower_bound,
                CASE
                    WHEN edge_type IN ('complement', 'mutually_exclusive') THEN 0.0
                    WHEN edge_type = 'implies' AND current_p_dst > 0 THEN current_p_src / current_p_dst
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
            FROM logic_edges_v
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
            FROM logic_edges_v
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
            FROM logic_edges_v
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
            JOIN current_pair_prices p USING (src_node_id, dst_node_id)
            LEFT JOIN logic_edges_v e USING (src_node_id, dst_node_id)
            WHERE e.src_node_id IS NULL
        )
        SELECT * FROM exact_rows
        UNION ALL
        SELECT * FROM frechet;

        COPY conditional_edges_v TO '{q(out_dir / "conditional_edges.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_violations(db: DuckDB, out_dir: Path) -> None:
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
                'same-market tokens do not sum to 1' AS description
            FROM candidate_edges_v c
            JOIN aligned_edges s USING (src_node_id, dst_node_id)
            JOIN current_pair_prices p USING (src_node_id, dst_node_id)
            WHERE c.candidate_type = 'complement'
                    AND (
                        abs(p.current_p_src + p.current_p_dst - 1) >= {T.COMPLEMENT_CURRENT_GAP_VIOLATION_MIN}
                        OR s.complement_error >= {T.COMPLEMENT_MEAN_GAP_VIOLATION_MIN}
                    )
        ),
        edge_violations AS (
            SELECT
                edge_type,
                src_node_id,
                dst_node_id,
                market_id_src,
                market_id_dst,
                event_slug_src,
                event_slug_dst,
                CASE
                    WHEN edge_type = 'equivalent' THEN abs(current_p_src - current_p_dst)
                    WHEN edge_type = 'implies' THEN greatest(0, current_p_src - current_p_dst)
                    WHEN edge_type = 'mutually_exclusive' THEN greatest(0, current_p_src + current_p_dst - 1)
                    ELSE 0
                END AS current_gap,
                violation_score AS mean_gap,
                evidence AS description
            FROM logic_edges_v
            WHERE
                (edge_type = 'equivalent' AND abs(current_p_src - current_p_dst) > {T.EQUIVALENCE_CURRENT_ABS_DIFF_MAX})
                OR (edge_type = 'implies' AND current_p_src > current_p_dst + {T.IMPLICATION_CURRENT_SLACK})
                OR (edge_type = 'mutually_exclusive' AND current_p_src + current_p_dst > {T.EXCLUSION_CURRENT_SUM_MAX})
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
            CASE WHEN current_gap >= 0.05 OR mean_gap >= 0.025 THEN 'high' ELSE 'medium' END AS severity,
            current_gap,
            mean_gap,
            greatest(0, 1 - 20 * mean_gap) AS confidence,
            NULL::TIMESTAMP WITH TIME ZONE AS first_seen_ts,
            NULL::TIMESTAMP WITH TIME ZONE AS last_seen_ts,
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
            CASE WHEN current_gap >= 0.05 THEN 'high' ELSE 'medium' END,
            current_gap,
            mean_gap,
            greatest(0, 1 - 20 * mean_gap),
            NULL::TIMESTAMP WITH TIME ZONE,
            NULL::TIMESTAMP WITH TIME ZONE,
            description
        FROM edge_violations;

        COPY violations_v TO '{q(out_dir / "violations.parquet")}' (FORMAT PARQUET);
        """
    )


def _stats(db: DuckDB, start: float) -> dict[str, str | int | float | None]:
    row = db.rows(
        """
        SELECT
            (SELECT count(*) FROM input_prices) AS input_rows,
            (SELECT count(DISTINCT market_id) FROM input_prices) AS markets,
            (SELECT count(DISTINCT clob_token_id) FROM input_prices) AS tokens,
            (SELECT min(odds_timestamp) FROM input_prices) AS time_range_start,
            (SELECT max(odds_timestamp) FROM input_prices) AS time_range_end,
            (SELECT count(*) FROM (SELECT market_id FROM input_prices GROUP BY market_id HAVING bool_or(is_active))) AS active_markets,
            (SELECT count(*) FROM (SELECT market_id FROM input_prices GROUP BY market_id HAVING bool_or(is_closed))) AS closed_markets,
            (SELECT count(*) FROM candidate_edges_v) AS candidate_edges,
            (SELECT count(*) FROM logic_edges_v) AS logic_edges,
            (SELECT count(*) FROM violations_v) AS violations
        """
    )[0]
    row["runtime_seconds"] = round(time.time() - start, 3)
    return row
