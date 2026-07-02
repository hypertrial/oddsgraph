from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar

T_ = TypeVar("T_")

from . import noise
from . import thresholds as T
from .calibration import apply_calibration_confidence, fit_calibration, thresholds_as_dict
from .coherence import compute_transitive_closure, solve_event_coherence
from .evaluate import run_evaluation
from .queries import DuckDB, q
from .reports import write_reports
from .rules import Taxonomy, load_taxonomy, single_winner_pattern_sql, single_winner_values_sql, stage_rules_values_sql
from .schema import validate_input

GENERATED_PARQUET_ARTIFACTS = (
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

GENERATED_REPORTS = (
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


def _stage(name: str, fn: Callable[[], T_]) -> T_:
    t0 = time.time()
    print(f"[oddsgraph] {name} ...", file=sys.stderr, flush=True)
    result = fn()
    print(f"[oddsgraph] {name} done in {time.time() - t0:.1f}s", file=sys.stderr, flush=True)
    return result


def build(
    input_path: Path,
    out_dir: Path,
    *,
    quotes_path: Path | None = None,
    resolutions_path: Path | None = None,
    taxonomy_path: Path | None = None,
) -> dict[str, str | int | float | None]:
    start = time.time()
    taxonomy = load_taxonomy(taxonomy_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    _clear_generated(out_dir)
    db_path = out_dir / "oddsgraph.duckdb"
    db = DuckDB(db_path)
    effective_thresholds = None
    lp_warnings: list[str] = []
    try:
        _stage("validate_input", lambda: validate_input(db, input_path))
        _stage("create_views", lambda: _create_views(db, input_path, taxonomy, quotes_path))
        _stage("write_prices", lambda: _write_prices(db, out_dir))
        _stage("write_nodes", lambda: _write_nodes(db, out_dir))
        _stage("write_market_groups", lambda: _write_market_groups(db, out_dir))
        _stage("write_candidates", lambda: _write_candidates(db, out_dir))
        _stage("score_edges", lambda: _score_edges(db, out_dir))
        effective_thresholds = _stage(
            "fit_calibration", lambda: fit_calibration(db, out_dir)
        )[1]
        _stage("apply_calibration_confidence", lambda: apply_calibration_confidence(db, effective_thresholds))
        _stage("write_final_edges", lambda: _write_final_edges(db, out_dir))
        _stage("compute_transitive_closure", lambda: compute_transitive_closure(db, out_dir))
        lp_warnings = _stage("solve_event_coherence", lambda: solve_event_coherence(db, out_dir))
        _stage("write_constraints", lambda: _write_constraints(db, out_dir))
        _stage("write_conditionals", lambda: _write_conditionals(db, out_dir))
        _stage("write_violations", lambda: _write_violations(db, out_dir, effective_thresholds))
        if resolutions_path is not None:
            _stage("run_evaluation", lambda: run_evaluation(db, out_dir, resolutions_path))
        stats = _stage("stats", lambda: _stats(db, start))
        _stage("write_reports", lambda: write_reports(db, out_dir, stats))
        _stage(
            "validate_generated_artifacts",
            lambda: _validate_generated_artifacts(db, out_dir, has_evaluation=resolutions_path is not None),
        )
        _write_manifest(
            input_path,
            out_dir,
            stats,
            taxonomy=taxonomy,
            quotes_path=quotes_path,
            resolutions_path=resolutions_path,
            effective_thresholds=effective_thresholds,
            lp_warnings=lp_warnings,
            has_evaluation=resolutions_path is not None,
        )
        return stats
    finally:
        db.close()


def _clear_generated(out_dir: Path) -> None:
    for name in (*GENERATED_PARQUET_ARTIFACTS, *OPTIONAL_PARQUET_ARTIFACTS, "build_manifest.json", "oddsgraph.duckdb"):
        path = out_dir / name
        if path.exists():
            path.unlink()
    for name in GENERATED_REPORTS:
        path = out_dir / "reports" / name
        if path.exists():
            path.unlink()


def _write_manifest(
    input_path: Path,
    out_dir: Path,
    stats: dict[str, object],
    *,
    taxonomy: Taxonomy,
    quotes_path: Path | None,
    resolutions_path: Path | None,
    effective_thresholds: object | None,
    lp_warnings: list[str],
    has_evaluation: bool,
) -> None:
    artifacts = list(GENERATED_PARQUET_ARTIFACTS)
    if has_evaluation:
        artifacts.append("evaluation.parquet")
    reports = [f"reports/{name}" for name in GENERATED_REPORTS if name != "evaluation.md" or has_evaluation]
    manifest = {
        "input": str(input_path),
        "quotes": str(quotes_path) if quotes_path else None,
        "resolutions": str(resolutions_path) if resolutions_path else None,
        "taxonomy": {
            "name": taxonomy.name,
            "path": str(taxonomy.source_path),
            "hash": taxonomy.content_hash,
        },
        "effective_thresholds": thresholds_as_dict(effective_thresholds) if effective_thresholds else None,
        "lp_warnings": lp_warnings,
        "artifacts": artifacts,
        "reports": reports,
        "stats": stats,
    }
    (out_dir / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _copy_table(db: DuckDB, out_dir: Path, table: str, artifact: str) -> None:
    db.execute(f"COPY {table} TO '{q(out_dir / artifact)}' (FORMAT PARQUET);")


def _write_final_edges(db: DuckDB, out_dir: Path) -> None:
    _copy_table(db, out_dir, "logic_edges_v", "logic_edges.parquet")
    _copy_table(db, out_dir, "price_edges_v", "price_edges.parquet")


def _validate_generated_artifacts(db: DuckDB, out_dir: Path, *, has_evaluation: bool) -> None:
    artifacts = list(GENERATED_PARQUET_ARTIFACTS)
    if has_evaluation:
        artifacts.extend(OPTIONAL_PARQUET_ARTIFACTS)
    missing = [name for name in artifacts if not (out_dir / name).exists()]
    if missing:
        raise RuntimeError("Missing generated artifacts: " + ", ".join(missing))

    for table, artifact in (
        ("logic_edges_v", "logic_edges.parquet"),
        ("price_edges_v", "price_edges.parquet"),
    ):
        table_count = int(db.scalar(f"SELECT count(*) FROM {table}") or 0)
        file_count = int(db.scalar(f"SELECT count(*) FROM read_parquet('{q(out_dir / artifact)}')") or 0)
        if table_count != file_count:
            raise RuntimeError(
                f"{artifact} is stale: table has {table_count} rows, artifact has {file_count}"
            )


def _create_views(
    db: DuckDB,
    input_path: Path,
    taxonomy: Taxonomy,
    quotes_path: Path | None,
) -> None:
    src = q(input_path)
    quotes_sql = q(quotes_path) if quotes_path else None
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
            CAST(floor(ODDS_TIMESTAMP_EPOCH / 60) * 60 AS BIGINT) AS odds_minute_epoch,
            price
        FROM read_parquet('{src}');
        """
    )
    _stage(
        "  token_minute_prices",
        lambda: db.execute(
            """
            CREATE TABLE token_minute_prices AS
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
                odds_timestamp,
                odds_timestamp_epoch,
                odds_minute_epoch,
                price
            FROM (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY clob_token_id, odds_minute_epoch
                        ORDER BY odds_timestamp_epoch DESC
                    ) AS rn
                FROM input_prices
            )
            WHERE rn = 1;
            """
        ),
    )
    _stage(
        "  enriched_minute_prices",
        lambda: db.execute(
            f"""
            {noise.create_quote_views_sql(quotes_sql)}
            {noise.create_enriched_minute_prices_sql()}
            """
        ),
    )
    db.execute(
        f"""
        CREATE TABLE semantic_stage_rules AS
        SELECT *
        FROM (VALUES
            {stage_rules_values_sql(taxonomy)}
        ) AS t(rule_pattern, stage_rank);

        CREATE TABLE semantic_single_winner_slugs AS
        SELECT *
        FROM (VALUES
            {single_winner_values_sql(taxonomy)}
        ) AS t(event_slug);

        CREATE TABLE market_token_counts AS
        SELECT market_id, count(DISTINCT clob_token_id) AS expected_tokens
        FROM input_prices
        GROUP BY market_id;

        CREATE TABLE market_complete_epochs AS
        WITH counts AS (
            SELECT
                market_id,
                odds_minute_epoch,
                count(DISTINCT clob_token_id) AS token_count
            FROM token_minute_prices
            GROUP BY 1, 2
        )
        SELECT c.market_id, max(c.odds_minute_epoch) AS current_minute_epoch
        FROM counts c
        JOIN market_token_counts t USING (market_id)
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
            max(price) AS max_price,
            avg(price_devig) AS mean_price_devig
        FROM enriched_minute_prices
        GROUP BY clob_token_id;

        CREATE TABLE token_current AS
        SELECT
            t.node_id,
            any_value(p.scoring_price) AS current_price,
            any_value(p.price_devig) AS current_price_devig,
            any_value(p.odds_timestamp) AS current_ts,
            any_value(p.odds_timestamp_epoch) AS current_epoch
        FROM (
            SELECT DISTINCT clob_token_id AS node_id, market_id
            FROM input_prices
        ) t
        LEFT JOIN market_complete_epochs e ON t.market_id = e.market_id
        LEFT JOIN enriched_minute_prices p
            ON p.market_id = t.market_id
            AND p.clob_token_id = t.node_id
            AND p.odds_minute_epoch = e.current_minute_epoch
        GROUP BY t.node_id;

        CREATE VIEW nodes_v AS
        WITH stage_matches AS (
            SELECT node_id, stage_subject, stage_rank
            FROM (
                SELECT
                    s.node_id,
                    regexp_extract(s.question, r.rule_pattern, 1) AS stage_subject,
                    r.stage_rank,
                    row_number() OVER (PARTITION BY s.node_id ORDER BY r.stage_rank DESC) AS rn
                FROM token_stats s
                JOIN semantic_stage_rules r
                    ON regexp_extract(s.question, r.rule_pattern, 1) != ''
            )
            WHERE rn = 1
        ),
        enriched AS (
            SELECT
                s.*,
                CASE
                    WHEN s.outcome_label = 'Yes' THEN s.question
                    WHEN s.outcome_label = 'No' THEN 'NOT(' || s.question || ')'
                    ELSE s.question || ' :: ' || s.outcome_label
                END AS canonical_proposition,
                CASE
                    WHEN s.outcome_label IN ('Yes', 'No') THEN 'binary'
                    ELSE 'named_outcome'
                END AS proposition_type,
                m.stage_subject,
                m.stage_rank,
                CASE
                    WHEN w.event_slug IS NOT NULL OR {single_winner_pattern_sql(taxonomy, "s.event_slug")} THEN true
                    ELSE false
                END AS is_single_winner_family,
                t.expected_tokens
            FROM token_stats s
            JOIN market_token_counts t USING (market_id)
            LEFT JOIN stage_matches m USING (node_id)
            LEFT JOIN semantic_single_winner_slugs w
                ON w.event_slug = s.event_slug
        )
        SELECT
            e.*,
            CASE
                WHEN e.is_single_winner_family THEN 'single_winner'
                WHEN e.stage_rank IS NOT NULL THEN 'stage_progression'
                ELSE 'unknown'
            END AS market_family,
            c.current_price,
            c.current_price_devig,
            c.current_epoch
        FROM enriched e
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
                price_devig,
                scoring_price,
                is_active,
                is_closed,
                market_volume_usd,
                ln(least(greatest(scoring_price, 0.0005), 0.9995) / (1 - least(greatest(scoring_price, 0.0005), 0.9995))) AS logit_price,
                scoring_price - lag(scoring_price) OVER (
                    PARTITION BY clob_token_id ORDER BY odds_minute_epoch
                ) AS price_return_1m
            FROM enriched_minute_prices
        ) TO '{q(out_dir / "prices.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_nodes(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        COPY (
            SELECT
                node_id, market_id, outcome_index, clob_token_id, question, outcome_label,
                event_slug, is_active, is_closed, market_volume_usd, market_family,
                canonical_proposition, proposition_type, expected_tokens,
                first_seen_ts, last_seen_ts, active_minutes, current_price, current_price_devig,
                mean_price, mean_price_devig, min_price, max_price
            FROM nodes_v
        ) TO '{q(out_dir / "nodes.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_market_groups(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        COPY (
            WITH sums AS (
                SELECT
                    p.market_id,
                    p.odds_minute_epoch,
                    sum(p.scoring_price) AS sum_price,
                    count(DISTINCT p.clob_token_id) AS token_count
                FROM enriched_minute_prices p
                GROUP BY 1, 2
            ),
            complete_sums AS (
                SELECT s.*
                FROM sums s
                JOIN market_token_counts t USING (market_id)
                WHERE s.token_count = t.expected_tokens
            ),
            current_sums AS (
                SELECT s.market_id, s.sum_price AS current_sum_price
                FROM complete_sums s
                JOIN market_complete_epochs e
                    ON s.market_id = e.market_id
                    AND s.odds_minute_epoch = e.current_minute_epoch
            )
            SELECT
                n.market_id,
                any_value(n.event_slug) AS event_slug,
                any_value(n.question) AS question,
                any_value(n.market_family) AS market_family,
                any_value(n.expected_tokens) AS num_tokens,
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
            LEFT JOIN complete_sums s USING (market_id)
            LEFT JOIN current_sums c USING (market_id)
            GROUP BY n.market_id
        ) TO '{q(out_dir / "market_groups.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_candidates(db: DuckDB, out_dir: Path) -> None:
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
    db.execute(f"COPY candidate_edges_v TO '{q(out_dir / 'candidate_edges.parquet')}' (FORMAT PARQUET);")


def _score_edges(db: DuckDB, out_dir: Path) -> None:
    _stage("  scoring_minute_prices", lambda: db.execute(noise.create_scoring_minute_prices_sql()))
    _stage("  aligned_edges", lambda: db.execute(noise.create_aligned_edges_sql()))
    _stage("  pair_persistence", lambda: db.execute(noise.create_pair_persistence_sql()))
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


def _write_constraints(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        COPY (
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
                SELECT market_id, avg(sum_price) AS mean_sum_price
                FROM (
                    SELECT
                        p.market_id,
                        p.odds_minute_epoch,
                        sum(p.scoring_price) AS sum_price,
                        count(DISTINCT p.clob_token_id) AS token_count
                    FROM enriched_minute_prices p
                    GROUP BY 1, 2
                ) s
                JOIN market_token_counts t USING (market_id)
                WHERE s.token_count = t.expected_tokens
                GROUP BY market_id
            ),
            current_sums AS (
                SELECT p.market_id, sum(p.scoring_price) AS current_sum_price
                FROM enriched_minute_prices p
                JOIN market_complete_epochs e
                    ON p.market_id = e.market_id
                    AND p.odds_minute_epoch = e.current_minute_epoch
                GROUP BY p.market_id
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
            LEFT JOIN current_sums c USING (market_id)
        ) TO '{q(out_dir / "constraint_hyperedges.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_conditionals(db: DuckDB, out_dir: Path) -> None:
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

        COPY conditional_edges_v TO '{q(out_dir / "conditional_edges.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_violations(db: DuckDB, out_dir: Path, effective) -> None:
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
            (SELECT count(*) FROM price_edges_v) AS price_edges,
            (SELECT count(*) FROM derived_edges_v) AS derived_edges,
            (SELECT count(*) FROM violations_v) AS violations,
            (SELECT count(*) FROM coherence_v WHERE incoherence_distance >= 0.05) AS incoherent_events
        """
    )[0]
    row["runtime_seconds"] = round(time.time() - start, 3)
    return row
