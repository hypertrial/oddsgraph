# Build Modes

The default build remains the compatibility contract. It writes the full current
artifact set and keeps historical statistics full-history unless a mode says
otherwise.

## Source Parquet

Generate the odds parquet with
[hypertrial/oddsfox-pipeline](https://github.com/hypertrial/oddsfox-pipeline). Follow its
[quickstart](https://github.com/hypertrial/oddsfox-pipeline/blob/main/docs/quickstart.md),
then export `polymarket_wc2026_marts.polymarket_wc2026_graph_token_hourly_odds`
as parquet with `scripts/export_polymarket_wc2026_graph_hourly_odds.py`.

The graph export includes both Yes/No tokens per real-team knockout market and
dbt-clean semantic columns such as `canonical_team_name`, `stage_key`,
`stage_rank`, `is_progression_token`, and `opposite_clob_token_id`. Historical
`selected_token_hourly_odds` parquet is still supported for audits, backtests,
and legacy fixtures; regex/taxonomy parsing is only used when semantic columns
are absent.
Legacy minutely parquet with `odds_timestamp`, `odds_timestamp_epoch`, and
`price` is still supported for compatibility.

## Full Build

```bash
python -m oddsfox_graph.cli build \
  --input "$ODDSFOX_DATA_DIR/exports/wc2026_graph_hourly.parquet" \
  --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026"
```

Full builds write all default parquet artifacts, all default reports, and
`build_manifest.json`. They materialize the full deduplicated price history for
`prices.parquet` and historical node and market statistics.

## Input Granularity And Thresholds

The build detects whether the source parquet is `minutely` or `hourly` and
normalizes both into the same internal `input_prices` shape. The manifest
records the detected `input_format` and `input_granularity_seconds`.

Threshold constants are duration intent, not literal row counts. The build
converts them to bucket counts from the detected granularity and records the
effective values in `threshold_bucket_counts`:

- `active_buckets`: active history required for price-signal candidates.
- `overlap_buckets`: aligned history required before accepting price-only
  relationships.
- `complement_low_overlap_buckets`: low-support complement confidence floor.
- `violation_persistence_buckets`: recent breach count required for reporting
  persistence-aware violations.
- `persistence_lookback_buckets`: duration-equivalent trailing window size.
- `persistence_lookback_seconds`: trailing window duration used in SQL.

Examples: a 1000-minute active/overlap threshold is `1000` buckets for minutely
input and `17` buckets for hourly input. A 30-minute violation persistence
threshold is `30` minutely buckets and `1` hourly bucket.

Public artifact column names remain unchanged for compatibility. With hourly
input, legacy names such as `active_minutes`, `overlap_minutes`,
`trailing_breach_minutes`, `trailing_window_minutes`, and `price_return_1m`
mean source price buckets and adjacent-bucket returns rather than literal
minutes.

## Optional Inputs

- `--quotes quotes.parquet`: optional bid/ask history with `clob_token_id`,
  `odds_timestamp_epoch`, `bid`, and `ask`. When provided, midpoint prices and
  half-spread noise floors are used for scoring.
- `--resolutions resolutions.parquet`: optional resolved outcomes with either
  `clob_token_id` or (`market_id`, `outcome_label`), plus `payout` and
  `resolved_at`. When provided, the build writes `evaluation.parquet` and
  `reports/evaluation.md`.
- `--taxonomy path.json`: event taxonomy for stage progression and
  single-winner families. Defaults to `oddsfox_graph/taxonomies/wc2026.json`.

## Live-Current Eligibility

By default, graph builds only admit markets whose latest complete source bucket
is active, not closed, and within `48` hours of the input's global max bucket.
This gate is applied before nodes, market groups, candidates, constraints,
edges, violations, and coherence are built.

Use `--current-max-age-hours N` to change the freshness window. Use
`--allow-stale-current` only for historical fixtures or backtests that
deliberately need legacy behavior.

## Optional Output Modes

### `--skip-prices`

Omits `prices.parquet`. Graph artifacts, reports, and query commands that read
nodes, edges, violations, or conditionals still work. Commands that require
`prices.parquet` report that it was intentionally not generated.

### `--skip-coherence`

Omits `coherence.parquet` and `coherence_repairs.parquet`. Conditional rows
fall back to current pair prices, and violations omit `global_incoherence`
rows. The `coherence` command reports that the artifact was intentionally not
generated and names `--skip-coherence`.

### `--fast-graph`

Opt-in graph inspection mode. It implies `write_prices=False` and
`solve_coherence=False`, so it omits `prices.parquet`, `coherence.parquet`, and
`coherence_repairs.parquet`. It preserves graph/query artifacts:
`nodes.parquet`, `market_groups.parquet`, `candidate_edges.parquet`,
`logic_edges.parquet`, `price_edges.parquet`, `derived_edges.parquet`,
`constraint_hyperedges.parquet`, `conditional_edges.parquet`,
`violations.parquet`, `calibration.parquet`, reports, and the manifest.

`--graph-lookback-days N` controls the fast graph history window. It defaults to
`30`, must be positive, and is only valid with `--fast-graph`.

Fast graph mode still computes current prices from each eligible market's latest
complete time bucket. Historical node fields such as `active_minutes`, `mean_price`,
`mean_price_devig`, `min_price`, `max_price`, and market fields such as
`mean_sum_price` are lookback-scoped. The manifest marks this with
`stats.history_mode = "fast_graph_lookback"`.

## Manifest Semantics

`build_manifest.json` is written last and is the completion marker for a coherent
output directory. It lists only artifacts and reports intentionally written by
that build.

Top-level manifest fields:

- `input`: input parquet path.
- `input_format`: detected source format, either `minutely` or `hourly`.
- `input_granularity_seconds`: detected source price bucket size.
- `quotes`: optional quotes path, or `null`.
- `resolutions`: optional resolutions path, or `null`.
- `taxonomy`: taxonomy metadata.
- `threshold_bucket_counts`: duration thresholds converted to source bucket
  counts.
- `effective_thresholds`: calibrated thresholds used for graph acceptance.
- `lp_warnings`: warnings emitted by event-level LP coherence.
- `build_options`: explicit options that affected artifact generation.
- `artifacts`: parquet artifact filenames written for this build.
- `reports`: markdown report paths written for this build.
- `stats`: summary counts and runtime metrics.
- `stage_timings`: elapsed seconds by build stage.

`taxonomy` contains:

- `name`
- `path`
- `hash`

`build_options` contains:

- `write_prices`
- `solve_coherence`
- `fast_graph`
- `graph_lookback_days`
- `current_max_age_hours`

`stats` includes graph counts, `history_mode`, current-market eligibility
counts, the global current epoch, and the minimum accepted current epoch.
`history_mode` is either `full` or `fast_graph_lookback`.

Query commands read the manifest before opening artifacts. That lets them
distinguish intentionally skipped artifacts from missing or stale output files.
