# Benchmarks

Benchmark notes are dated local measurements, not a portable performance
guarantee. Hardware, DuckDB version, source parquet shape, and filesystem state
can all move timings materially.

## Methodology

Use a fresh ignored output directory for each run:

```bash
python -m oddsgraph.cli build \
  --input wc2026_token_minutely_odds_20260702T070755Z.parquet \
  --out output/perf_full
```

```bash
python -m oddsgraph.cli build \
  --input wc2026_token_minutely_odds_20260702T070755Z.parquet \
  --out output/perf_fast_graph \
  --fast-graph \
  --graph-lookback-days 30
```

Summarize a completed run:

```bash
python -m oddsgraph.cli benchmark-summary --out output/perf_fast_graph
```

Run a paired full/fast graph comparison:

```bash
python -m oddsgraph.cli benchmark-compare \
  --input wc2026_token_minutely_odds_20260702T070755Z.parquet \
  --out-root output/debt_pr_benchmark \
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
`wc2026_token_minutely_odds_20260702T070755Z.parquet`, 53,827,798 input rows.

Date: July 2 2026. Commit context: post fast-graph performance PR.

| mode | output dir | runtime | size | candidates | logic | price | violations | history mode |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| full | `output/perf_after_full_final3` | 444.189s | 3.2G | 16,684 | 7,842 | 5,325 | 9 | `full` |
| fast graph, 30 days | `output/perf_after_fast_graph_final` | 111.717s | 917M | 15,118 | 7,842 | 5,325 | 0 | `fast_graph_lookback` |

Top full-build stages:

| stage | seconds |
| --- | ---: |
| `create_views` | 317.752 |
| `token_minute_prices` | 206.043 |
| `enriched_minute_prices` | 76.067 |
| `score_edges` | 39.754 |
| `write_prices` | 34.206 |
| `market_completeness` | 26.490 |
| `create_input_prices` | 20.319 |
| `scoring_minute_prices` | 16.179 |

Top fast-graph stages:

| stage | seconds |
| --- | ---: |
| `create_views` | 40.824 |
| `score_edges` | 33.756 |
| `create_input_prices` | 20.241 |
| `token_minute_prices` | 20.136 |
| `enriched_minute_prices` | 16.050 |
| `aligned_edges` | 14.180 |
| `scoring_minute_prices` | 12.540 |
| `validate_input` | 12.274 |

## Historical Baselines

- Active full-build gate before the fast-graph PR: 401.205s.
- Earlier full-build benchmark: 363.454s.
- Previous graph-inspection workflow with `--skip-prices --skip-coherence`:
  332.928s.

The post fast-graph full run did not beat the active 401.205s gate. The main
regressions were full-history token-minute dedupe at 206.043s versus a 154.391s
baseline and `prices.parquet` export at 34.206s versus a 22.278s baseline.

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
