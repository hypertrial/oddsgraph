# Benchmarks

Benchmark notes are dated local measurements, not a portable performance
guarantee. Hardware, DuckDB version, source parquet shape, and filesystem state
can all move timings materially.

## Methodology

Use a fresh ignored output directory for each run:

```bash
python -m oddsfox_graph.cli build \
  --input "$ODDSFOX_DATA_DIR/exports/wc2026_graph_hourly.parquet" \
  --out "$ODDSFOX_DATA_DIR/artifacts/manual/perf_full"
```

```bash
python -m oddsfox_graph.cli build \
  --input "$ODDSFOX_DATA_DIR/exports/wc2026_graph_hourly.parquet" \
  --out "$ODDSFOX_DATA_DIR/artifacts/manual/perf_fast_graph" \
  --fast-graph \
  --graph-lookback-days 30
```

Summarize a completed run:

```bash
python -m oddsfox_graph.cli benchmark-summary --out "$ODDSFOX_DATA_DIR/artifacts/manual/perf_fast_graph"
```

Run a paired full/fast graph comparison:

```bash
python -m oddsfox_graph.cli benchmark-compare \
  --input "$ODDSFOX_DATA_DIR/exports/wc2026_graph_hourly.parquet" \
  --out-root "$ODDSFOX_DATA_DIR/artifacts/manual/debt_pr_benchmark" \
  --graph-lookback-days 30
```

To compare against a previous paired run, pass its
`benchmark_compare.json` with `--baseline-json`. Runtime deltas are printed and
stored, but the command does not fail on noisy local timing changes.

Record:

- runtime seconds from `stats.runtime_seconds`.
- `stats.history_mode`.
- graph counts from `stats`.
- generated artifact count.
- output directory size.
- top `stage_timings`.
- source parquet name, date, and commit context.

## Latest Local WC2026 Results

Source:
`selected_token_hourly_odds_20260703T095031Z.parquet`, 1,094,140 input rows.

Date: July 3 2026. Commit context: local working tree with duration-scaled
hourly thresholds and WC2026 stage aliases.

| mode | output dir | runtime | size | candidates | logic | price | violations | history mode |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| full | `output/hourly_pr_full` | 9.069s | 108M | 29,937 | 7,375 | 12,785 | 7 | `full` |
| fast graph, 30 days | `output/hourly_pr_fast` | 5.807s | 52M | 29,478 | 7,375 | 12,785 | 0 | `fast_graph_lookback` |

The manifest recorded `input_format = "hourly"`,
`input_granularity_seconds = 3600`, and duration-scaled thresholds:
`active_buckets = 17`, `overlap_buckets = 17`,
`complement_low_overlap_buckets = 1`, `violation_persistence_buckets = 1`, and
`persistence_lookback_buckets = 3`.

Compared with the first hourly migration run, price-only edges increased from
`0` to `12,785`. The earlier run interpreted the 1000-minute overlap threshold
as 1000 hourly buckets; this run converts the same duration intent to 17 hourly
buckets.

Top full-build stages:

| stage | seconds |
| --- | ---: |
| `create_views` | 3.471 |
| `score_edges` | 1.915 |
| `enriched_minute_prices` | 1.844 |
| `token_minute_prices` | 1.182 |
| `write_reports` | 0.931 |
| `apply_calibration_confidence` | 0.848 |
| `write_candidates` | 0.678 |
| `scoring_minute_prices` | 0.659 |

Top fast-graph stages:

| stage | seconds |
| --- | ---: |
| `score_edges` | 1.853 |
| `create_views` | 1.364 |
| `write_reports` | 0.925 |
| `apply_calibration_confidence` | 0.889 |
| `write_candidates` | 0.669 |
| `aligned_edges` | 0.606 |
| `scoring_minute_prices` | 0.596 |
| `enriched_minute_prices` | 0.512 |

## Historical Baselines

- Active full-build gate before the fast-graph PR: 401.205s.
- Earlier full-build benchmark: 363.454s.
- Previous graph-inspection workflow with `--skip-prices --skip-coherence`:
  332.928s.
- Last minutely full result before the hourly input switch:
  `wc2026_token_minutely_odds_20260702T070755Z.parquet` with 53,827,798 input
  rows, 444.189s full runtime, and 111.717s fast-graph runtime.

In that last minutely run, the post fast-graph full build did not beat the
active 401.205s gate. The main regressions were full-history token-minute
dedupe at 206.043s versus a 154.391s baseline and `prices.parquet` export at
34.206s versus a 22.278s baseline.

## Accepted And Rejected Optimizations

Accepted:

- Manifest `stage_timings`, so future performance discussions use measured
  stages rather than whole-run guesses.
- `benchmark-summary`, so completed runs can be summarized without opening
  parquet files manually.
- Sparse LP coherence setup and batched event data collection. In the measured
  run, `solve_event_coherence` dropped from 71.512s to about 0.8s.
- `--fast-graph`, which makes graph inspection materially faster by avoiding
  full-history price export and coherence output.

Rejected or left out of the default hot path:

- Grouped `arg_max` token-minute dedupe, because it did not preserve the exact
  latest-timestamp semantics under all required checks.
- Narrow max-join token-minute dedupe, because it did not clear parity and local
  performance gates strongly enough to replace the existing window query.
- Materialized full-history market-minute sums in the default path, because the
  added materialization cost outweighed reuse in the measured full build.

## Updating This Page

Do not put benchmark tables in the README. Update this page when benchmark
numbers intentionally change, and keep each result tied to a date, output
directory, source parquet, and commit context.
