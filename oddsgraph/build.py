from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable, TypeVar

T_ = TypeVar("T_")

from . import noise
from .artifacts import ARTIFACT_COLUMNS, FINAL_EDGE_ARTIFACT_TABLES, REPORTS, artifact_projection, parquet_artifacts, reports
from ._diagnostic_stages import write_conditionals, write_constraints, write_violations
from ._edge_stages import score_edges, write_candidates
from .calibration import apply_calibration_confidence, fit_calibration, thresholds_as_dict
from .coherence import compute_transitive_closure, create_empty_coherence_tables, solve_event_coherence
from .contracts import validate_relation_columns
from .evaluate import run_evaluation
from .queries import DuckDB, q
from .reports import write_reports
from .rules import Taxonomy, load_taxonomy, single_winner_pattern_sql, single_winner_values_sql, stage_rules_values_sql
from .schema import validate_input_schema, validate_input_table


def _stage(
    name: str,
    fn: Callable[[], T_],
    timings: dict[str, float] | None = None,
) -> T_:
    t0 = time.time()
    print(f"[oddsgraph] {name} ...", file=sys.stderr, flush=True)
    result = fn()
    elapsed = time.time() - t0
    if timings is not None:
        timings[name.strip()] = round(elapsed, 3)
    print(f"[oddsgraph] {name} done in {elapsed:.1f}s", file=sys.stderr, flush=True)
    return result


def build(
    input_path: Path,
    out_dir: Path,
    *,
    quotes_path: Path | None = None,
    resolutions_path: Path | None = None,
    taxonomy_path: Path | None = None,
    write_prices: bool = True,
    solve_coherence: bool = True,
    fast_graph: bool = False,
    graph_lookback_days: int = 30,
) -> dict[str, str | int | float | None]:
    if graph_lookback_days <= 0:
        raise ValueError("graph_lookback_days must be positive")
    actual_write_prices = write_prices and not fast_graph
    actual_solve_coherence = solve_coherence and not fast_graph
    start = time.time()
    taxonomy = load_taxonomy(taxonomy_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    _clear_generated(out_dir)
    db_path = out_dir / "oddsgraph.duckdb"
    db = DuckDB(db_path)
    effective_thresholds = None
    lp_warnings: list[str] = []
    stage_timings: dict[str, float] = {}

    def stage(name: str, fn: Callable[[], T_]) -> T_:
        return _stage(name, fn, stage_timings)

    try:
        stage("validate_input_schema", lambda: validate_input_schema(db, input_path))
        stage("create_input_prices", lambda: _create_input_prices(db, input_path))
        stage("validate_input", lambda: validate_input_table(db))
        stage(
            "create_views",
            lambda: _create_views(
                db,
                taxonomy,
                quotes_path,
                stage,
                fast_graph=fast_graph,
                graph_lookback_days=graph_lookback_days,
            ),
        )
        if actual_write_prices:
            stage("write_prices", lambda: _write_prices(db, out_dir))
        stage("write_nodes", lambda: _write_nodes(db, out_dir))
        stage("write_market_groups", lambda: _write_market_groups(db, out_dir))
        stage("write_candidates", lambda: write_candidates(db, out_dir))
        stage(
            "score_edges",
            lambda: score_edges(
                db,
                out_dir,
                stage,
                lookback_days=graph_lookback_days if fast_graph else None,
            ),
        )
        effective_thresholds = stage(
            "fit_calibration", lambda: fit_calibration(db, out_dir)
        )[1]
        stage("apply_calibration_confidence", lambda: apply_calibration_confidence(db, effective_thresholds))
        stage("validate_final_edges", lambda: _validate_final_edge_invariants(db))
        stage("write_final_edges", lambda: _write_final_edges(db, out_dir))
        stage("compute_transitive_closure", lambda: compute_transitive_closure(db, out_dir))
        if actual_solve_coherence:
            lp_warnings = stage("solve_event_coherence", lambda: solve_event_coherence(db, out_dir))
        else:
            stage("create_empty_coherence_tables", lambda: create_empty_coherence_tables(db))
        stage("write_constraints", lambda: write_constraints(db, out_dir))
        stage("write_conditionals", lambda: write_conditionals(db, out_dir))
        stage("write_violations", lambda: write_violations(db, out_dir, effective_thresholds))
        if resolutions_path is not None:
            stage("run_evaluation", lambda: run_evaluation(db, out_dir, resolutions_path))
        stats = stage("stats", lambda: _stats(db, start, fast_graph=fast_graph))
        stage("write_reports", lambda: write_reports(db, out_dir, stats))
        stage(
            "validate_generated_artifacts",
            lambda: _validate_generated_artifacts(
                db,
                out_dir,
                has_evaluation=resolutions_path is not None,
                has_prices=actual_write_prices,
                has_coherence=actual_solve_coherence,
            ),
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
            has_prices=actual_write_prices,
            has_coherence=actual_solve_coherence,
            fast_graph=fast_graph,
            graph_lookback_days=graph_lookback_days,
            stage_timings=stage_timings,
        )
        return stats
    finally:
        db.close()


def _clear_generated(out_dir: Path) -> None:
    for name in (*parquet_artifacts(has_evaluation=True), "build_manifest.json", "oddsgraph.duckdb"):
        path = out_dir / name
        if path.exists():
            path.unlink()
    for name in REPORTS:
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
    has_prices: bool,
    has_coherence: bool,
    fast_graph: bool,
    graph_lookback_days: int,
    stage_timings: dict[str, float],
) -> None:
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
        "build_options": {
            "write_prices": has_prices,
            "solve_coherence": has_coherence,
            "fast_graph": fast_graph,
            "graph_lookback_days": graph_lookback_days,
        },
        "artifacts": list(
            parquet_artifacts(
                has_evaluation=has_evaluation,
                has_prices=has_prices,
                has_coherence=has_coherence,
            )
        ),
        "reports": list(reports(has_evaluation=has_evaluation)),
        "stats": stats,
        "stage_timings": stage_timings,
    }
    (out_dir / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _copy_table(db: DuckDB, out_dir: Path, table: str, artifact: str) -> None:
    db.execute(
        f"""
        COPY (
            SELECT {artifact_projection(artifact)}
            FROM {table}
        ) TO '{q(out_dir / artifact)}' (FORMAT PARQUET);
        """
    )


def _write_final_edges(db: DuckDB, out_dir: Path) -> None:
    for artifact, table in FINAL_EDGE_ARTIFACT_TABLES.items():
        _copy_table(db, out_dir, table, artifact)


def _validate_generated_artifacts(
    db: DuckDB,
    out_dir: Path,
    *,
    has_evaluation: bool,
    has_prices: bool = True,
    has_coherence: bool = True,
) -> None:
    artifacts = parquet_artifacts(
        has_evaluation=has_evaluation,
        has_prices=has_prices,
        has_coherence=has_coherence,
    )
    missing = [name for name in artifacts if not (out_dir / name).exists()]
    if missing:
        raise RuntimeError("Missing generated artifacts: " + ", ".join(missing))

    for artifact in artifacts:
        expected_columns = ARTIFACT_COLUMNS[artifact]
        path = q(out_dir / artifact)
        actual_columns = [
            str(row["column_name"])
            for row in db.rows(f"DESCRIBE SELECT * FROM read_parquet('{path}')")
        ]
        if actual_columns != expected_columns:
            raise RuntimeError(
                f"{artifact} schema drift: expected {expected_columns}, got {actual_columns}"
            )

    for artifact, table in FINAL_EDGE_ARTIFACT_TABLES.items():
        table_count = int(db.scalar(f"SELECT count(*) FROM {table}") or 0)
        file_count = int(db.scalar(f"SELECT count(*) FROM read_parquet('{q(out_dir / artifact)}')") or 0)
        if table_count != file_count:
            raise RuntimeError(
                f"{artifact} is stale: table has {table_count} rows, artifact has {file_count}"
            )


def _create_input_prices(db: DuckDB, input_path: Path) -> None:
    src = q(input_path)
    db.execute(
        f"""
        CREATE TEMP TABLE input_prices AS
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
    validate_relation_columns(db, "input_prices")


def _create_views(
    db: DuckDB,
    taxonomy: Taxonomy,
    quotes_path: Path | None,
    stage: Callable[[str, Callable[[], T_]], T_],
    *,
    fast_graph: bool,
    graph_lookback_days: int,
) -> None:
    stage(
        "  token_minute_prices",
        lambda: _create_token_minute_prices(
            db,
            fast_graph=fast_graph,
            graph_lookback_days=graph_lookback_days,
        ),
    )
    stage("  validate_token_minute_prices", lambda: _validate_token_minute_prices(db))
    stage("  enriched_minute_prices", lambda: _create_enriched_minute_prices(db, quotes_path))
    stage("  semantic_tables", lambda: _create_semantic_tables(db, taxonomy))
    stage("  market_completeness", lambda: _create_market_minute_tables(db))
    stage("  token_stats", lambda: _create_token_stats_tables(db))
    stage("  validate_token_current", lambda: _validate_token_current(db))
    stage("  nodes_view", lambda: _create_nodes_view(db, taxonomy))
    stage("  validate_nodes", lambda: _validate_nodes(db))


def _create_token_minute_prices(
    db: DuckDB,
    *,
    fast_graph: bool = False,
    graph_lookback_days: int = 30,
) -> None:
    if not fast_graph:
        db.execute(
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
        )
        validate_relation_columns(db, "token_minute_prices")
        return

    lookback_seconds = graph_lookback_days * 24 * 3600
    source_sql = f"""
        WITH bounds AS (
            SELECT max(odds_minute_epoch) - {lookback_seconds} AS min_epoch
            FROM input_prices
        ),
        expected AS (
            SELECT market_id, count(DISTINCT clob_token_id) AS expected_tokens
            FROM input_prices
            GROUP BY market_id
        ),
        complete_epochs AS (
            SELECT p.market_id, p.odds_minute_epoch
            FROM input_prices p
            JOIN expected e USING (market_id)
            GROUP BY p.market_id, p.odds_minute_epoch, e.expected_tokens
            HAVING count(DISTINCT p.clob_token_id) = e.expected_tokens
        ),
        current_complete AS (
            SELECT market_id, max(odds_minute_epoch) AS current_minute_epoch
            FROM complete_epochs
            GROUP BY market_id
        )
        SELECT p.*
        FROM input_prices p
        CROSS JOIN bounds b
        LEFT JOIN current_complete c USING (market_id)
        WHERE p.odds_minute_epoch >= b.min_epoch
            OR p.odds_minute_epoch = c.current_minute_epoch
    """
    db.execute(
        f"""
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
            FROM (
                {source_sql}
            )
        )
        WHERE rn = 1;
        """
    )
    validate_relation_columns(db, "token_minute_prices")


def _create_enriched_minute_prices(db: DuckDB, quotes_path: Path | None) -> None:
    quotes_sql = q(quotes_path) if quotes_path else None
    db.execute(
        f"""
        {noise.create_quote_views_sql(quotes_sql)}
        {noise.create_enriched_minute_prices_sql()}
        """
    )
    validate_relation_columns(db, "quote_minute_prices")
    validate_relation_columns(db, "enriched_minute_prices")


def _create_semantic_tables(db: DuckDB, taxonomy: Taxonomy) -> None:
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
        """
    )


def _create_market_minute_tables(db: DuckDB) -> None:
    db.execute(
        """
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

        CREATE VIEW market_minute_sums AS
        SELECT
            p.market_id,
            p.odds_minute_epoch,
            count(*) AS token_count,
            t.expected_tokens,
            sum(p.price) AS raw_price_sum,
            sum(p.scoring_price) AS scoring_price_sum,
            count(*) = t.expected_tokens AS is_complete,
            p.odds_minute_epoch = e.current_minute_epoch AS is_current_complete
        FROM enriched_minute_prices p
        JOIN market_token_counts t USING (market_id)
        LEFT JOIN market_complete_epochs e USING (market_id)
        GROUP BY p.market_id, p.odds_minute_epoch, t.expected_tokens, e.current_minute_epoch;
        """
    )
    validate_relation_columns(db, "market_token_counts")
    validate_relation_columns(db, "market_complete_epochs")
    validate_relation_columns(db, "market_minute_sums")
    _require_zero(db, "markets without complete current minute", """
        SELECT count(*)
        FROM market_token_counts t
        LEFT JOIN market_complete_epochs e USING (market_id)
        WHERE e.market_id IS NULL
    """)


def _create_token_stats_tables(db: DuckDB) -> None:
    db.execute(
        """
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
        """
    )
    validate_relation_columns(db, "token_stats")
    validate_relation_columns(db, "token_current")


def _create_nodes_view(db: DuckDB, taxonomy: Taxonomy) -> None:
    db.execute(
        f"""
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
    validate_relation_columns(db, "nodes_v")


def _validate_token_minute_prices(db: DuckDB) -> None:
    _require_zero(db, "duplicate token-minute rows", """
        SELECT count(*)
        FROM (
            SELECT clob_token_id, odds_minute_epoch
            FROM token_minute_prices
            GROUP BY 1, 2
            HAVING count(*) > 1
        )
    """)


def _validate_token_current(db: DuckDB) -> None:
    _require_zero(db, "tokens without current prices", """
        SELECT count(*)
        FROM token_current
        WHERE current_epoch IS NULL OR current_price IS NULL
    """)


def _validate_nodes(db: DuckDB) -> None:
    _require_zero(db, "duplicate nodes", """
        SELECT count(*)
        FROM (
            SELECT node_id
            FROM nodes_v
            GROUP BY 1
            HAVING count(*) > 1
        )
    """)
    _require_zero(db, "node/token mismatch", """
        WITH input_tokens AS (
            SELECT DISTINCT clob_token_id AS node_id FROM input_prices
        ),
        nodes AS (
            SELECT node_id FROM nodes_v
        )
        SELECT count(*)
        FROM input_tokens i
        FULL OUTER JOIN nodes n USING (node_id)
        WHERE i.node_id IS NULL OR n.node_id IS NULL
    """)


def _validate_final_edge_invariants(db: DuckDB) -> None:
    failures = [
        ("duplicate logic edges", _count_invariant(db, """
            SELECT count(*)
            FROM (
                SELECT src_node_id, dst_node_id, edge_type
                FROM logic_edges_v
                GROUP BY 1, 2, 3
                HAVING count(*) > 1
            )
        """)),
        ("duplicate price edges", _count_invariant(db, """
            SELECT count(*)
            FROM (
                SELECT src_node_id, dst_node_id, edge_type
                FROM price_edges_v
                GROUP BY 1, 2, 3
                HAVING count(*) > 1
            )
        """)),
        ("logic/price edge overlap", _count_invariant(db, """
            SELECT count(*)
            FROM logic_edges_v l
            JOIN price_edges_v p
                ON l.src_node_id = p.src_node_id
                AND l.dst_node_id = p.dst_node_id
                AND l.edge_type = p.edge_type
        """)),
    ]
    failed = [f"{name}: {count}" for name, count in failures if count]
    if failed:
        raise RuntimeError("Final edge invariant failed: " + "; ".join(failed))


def _require_zero(db: DuckDB, name: str, sql: str) -> None:
    count = _count_invariant(db, sql)
    if count:
        raise RuntimeError(f"{name}: {count}")


def _count_invariant(db: DuckDB, sql: str) -> int:
    return int(db.scalar(sql) or 0)


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
                {artifact_projection("nodes.parquet")}
            FROM nodes_v
        ) TO '{q(out_dir / "nodes.parquet")}' (FORMAT PARQUET);
        """
    )


def _write_market_groups(db: DuckDB, out_dir: Path) -> None:
    db.execute(
        f"""
        COPY (
            SELECT {artifact_projection("market_groups.parquet")}
            FROM (
            WITH sums AS (
                SELECT
                    market_id,
                    odds_minute_epoch,
                    scoring_price_sum AS sum_price
                FROM market_minute_sums
                WHERE is_complete
            ),
            current_sums AS (
                SELECT market_id, scoring_price_sum AS current_sum_price
                FROM market_minute_sums
                WHERE is_current_complete
            ),
            mean_sums AS (
                SELECT market_id, avg(sum_price) AS mean_sum_price
                FROM sums
                GROUP BY market_id
            ),
            node_groups AS (
                SELECT
                    market_id,
                    any_value(event_slug) AS event_slug,
                    any_value(question) AS question,
                    any_value(market_family) AS market_family,
                    any_value(expected_tokens) AS num_tokens,
                    list(node_id ORDER BY outcome_index) AS token_ids,
                    list(outcome_label ORDER BY outcome_index) AS outcome_labels,
                    bool_or(is_active) AS is_active,
                    bool_or(is_closed) AS is_closed,
                    max(market_volume_usd) AS market_volume_usd,
                    min(first_seen_ts) AS first_seen_ts,
                    max(last_seen_ts) AS last_seen_ts
                FROM nodes_v
                GROUP BY market_id
            )
            SELECT
                n.market_id,
                n.event_slug,
                n.question,
                n.market_family,
                n.num_tokens,
                n.token_ids,
                n.outcome_labels,
                n.is_active,
                n.is_closed,
                n.market_volume_usd,
                n.first_seen_ts,
                n.last_seen_ts,
                c.current_sum_price,
                m.mean_sum_price
            FROM node_groups n
            LEFT JOIN mean_sums m USING (market_id)
            LEFT JOIN current_sums c USING (market_id)
            ) AS market_groups
        ) TO '{q(out_dir / "market_groups.parquet")}' (FORMAT PARQUET);
        """
    )


def _stats(
    db: DuckDB,
    start: float,
    *,
    fast_graph: bool = False,
) -> dict[str, str | int | float | None]:
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
    row["history_mode"] = "fast_graph_lookback" if fast_graph else "full"
    return row
