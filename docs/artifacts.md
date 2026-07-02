# oddsgraph Artifacts

The build writes parquet artifacts and markdown reports under the `--out`
directory. The graph node id is always `clob_token_id`, exposed as `node_id`.
`market_id` is a market container, not the graph node.
Successful builds write `build_manifest.json` last. Treat its presence as the
completion marker for a coherent output directory.

## Optional Inputs

- `--quotes quotes.parquet`: optional bid/ask history with `clob_token_id`,
  `odds_timestamp_epoch`, `bid`, `ask`. When provided, midpoint prices and
  half-spread noise floors are used for scoring.
- `--resolutions resolutions.parquet`: optional resolved outcomes with
  `clob_token_id` or (`market_id`, `outcome_label`), `payout`, `resolved_at`.
  When provided, the build also writes `evaluation.parquet` and
  `reports/evaluation.md`.
- `--taxonomy path.json`: event taxonomy for stage progression and single-winner
  families. Defaults to bundled `oddsgraph/taxonomies/wc2026.json`.

## Optional Outputs

- `--skip-prices`: omits `prices.parquet`. Graph artifacts, reports, and query
  commands that read nodes/edges/violations/conditionals still work.
- `--skip-coherence`: omits `coherence.parquet` and
  `coherence_repairs.parquet`. Conditional rows fall back to current pair prices,
  and violations omit `global_incoherence` rows.
- Skipped artifacts are intentionally absent and are not listed in
  `build_manifest.json`.

## Generated Parquet Files

### `nodes.parquet`

- Grain: one row per `clob_token_id`.
- Purpose: canonical proposition table for graph nodes.
- Important columns: `node_id`, `market_id`, `outcome_index`, `question`,
  `outcome_label`, `event_slug`, `canonical_proposition`, `proposition_type`,
  `expected_tokens`, `market_family`, `first_seen_ts`, `last_seen_ts`,
  `active_minutes`, `current_price`, `current_price_devig`, `mean_price`,
  `mean_price_devig`, `min_price`, `max_price`.

### `prices.parquet` (optional with `--skip-prices`)

- Grain: one row per `(node_id, odds_minute_epoch)` after deduplication.
- Purpose: minute-level price series with devig and scoring prices.
- Important columns: `price`, `price_devig`, `scoring_price`, `logit_price`,
  `price_return_1m`.

### `market_groups.parquet`

- Grain: one row per `market_id`.
- Purpose: market-level grouping and sum diagnostics for binary and n-ary markets.
- Important columns: `num_tokens`, `token_ids`, `current_sum_price`,
  `mean_sum_price`.

### `candidate_edges.parquet`

- Grain: one row per `(src_node_id, dst_node_id, candidate_type)`.
- Candidate sources: `same_market`, `exact_duplicate_same_event`,
  `semantic_single_winner`, `semantic_stage_progression`, `price_same_event_slug`.

### `logic_edges.parquet`

- Strict semantic/structural edges only (`edge_basis != price_only`).
- Edge bases: `same_market`, `exact_duplicate`, `single_winner_family`,
  `stage_progression_rule`.

### `price_edges.parquet`

- Price-threshold relationships not promoted to logic (`edge_basis = price_only`).

### `derived_edges.parquet`

- Transitive closure of accepted `implies` logic edges.
- Columns include `path` (provenance chain) and `edge_basis = transitive`.

### `constraint_hyperedges.parquet`

- Market-level constraints: `complement_pair` for binary markets, `one_of_n` for
  n-ary markets (expected sum 1).

### `conditional_edges.parquet`

- Exact conditionals from logic/derived edges; Fréchet bounds from repaired
  prices for unrelated pairs.
- `exact_implication_reverse` values are clamped to `[0, 1]`.

### `violations.parquet`

- Persistence-aware violations requiring breach streaks over recent aligned minutes.
- `confidence` is the recent breach fraction (higher means more persistent).
- `global_incoherence` rows come from per-event LP repair distance.

### `calibration.parquet`

- Empirical complement-noise buckets by liquidity and derived threshold quantiles.

### `coherence.parquet` (optional with `--skip-coherence`)

- Per `event_slug` LP repair summary: node count, constraint count,
  `incoherence_distance`, `solver_status`.

### `coherence_repairs.parquet` (optional with `--skip-coherence`)

- Per-node observed vs repaired prices from the event-level L1 coherence solve.

### `evaluation.parquet` (optional)

- Written when `--resolutions` is provided.
- Metrics: edge precision by basis, violation follow-through, Brier score buckets.

## Methodology Notes

- Pair scoring aligns on deduplicated minute buckets (`token_minute_prices`).
- EW gap stats and overlap counts use a trailing `SCORING_LOOKBACK_DAYS` window
  (default 30 days). Older minutes contribute negligible weight at the 7-day
  half-life but would otherwise multiply pair-minute rows on year-long feeds.
- Persistence scans only the last `PERSISTENCE_LOOKBACK_MINUTES` per pair and
  reuses `pair_max_epoch` from `aligned_edges` instead of rescanning history.
- Error metrics use exponentially weighted means (half-life in `thresholds.py`).
- Confidence scores are empirical p-values from complement-pair noise buckets.
- Global coherence solves `min sum |x - p|` subject to accepted logic constraints
  per event using SciPy HiGHS.
- Effective thresholds used at build time are recorded in `build_manifest.json`.

## Manifest

`build_manifest.json` records input paths, build options, taxonomy hash,
effective thresholds, LP warnings, generated artifacts/reports, and summary
stats. Its artifact list is the contract for that build, so omitted optional
artifacts are not validation failures.
