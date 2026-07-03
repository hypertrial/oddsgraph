# oddsgraph

`oddsgraph` turns token-hour Polymarket odds into graph-ready parquet
artifacts. Each `clob_token_id` becomes a proposition node, then the batch build
emits market groups, logical edges, price-only edges, derived implications,
conditional probabilities, constraint rows, violations, optional coherence and
evaluation artifacts, and markdown reports.

This is a Python/DuckDB tool for offline analysis. It is not a live ingest or
trading system.

## Requirements

- Python 3.11 or newer.
- DuckDB from the Python package dependency in `pyproject.toml`.
- A parquet input with the schema described in
  [selected_token_hourly_odds_20260703T095031Z.md](selected_token_hourly_odds_20260703T095031Z.md).

The local WC2026 hourly parquet is a sample, about 41 MB. It is useful for
reproducing the project results, but generated outputs and large datasets should
stay outside source control.

## Get The Parquet

Use [hypertrial/oddsfox](https://github.com/hypertrial/oddsfox) to build and
export the source data. OddsFox documents the local pipeline in its
[quickstart](https://github.com/hypertrial/oddsfox/blob/main/docs/quickstart.md).
For graph builds, export
`polymarket_marts.selected_token_live_hourly_odds` as parquet from OddsFox
(`scripts/export_selected_hourly_odds.py --live-current`). The historical
`selected_token_hourly_odds` export remains useful for audits and backtests;
`oddsgraph` also defensively filters stale or closed markets by default.

The exported parquet should match the schema in
[selected_token_hourly_odds_20260703T095031Z.md](selected_token_hourly_odds_20260703T095031Z.md).

## Setup

From the repo root:

```bash
python -m pip install -e ".[dev]"
```

## Build Artifacts

Run a full build when you want the complete artifact set:

```bash
python -m oddsgraph.cli build \
  --input selected_token_live_hourly_odds_20260703T095031Z.parquet \
  --out output/wc2026
```

Run fast graph mode when you want graph/query artifacts quickly and can accept
lookback-scoped historical node and market statistics:

```bash
python -m oddsgraph.cli build \
  --input selected_token_live_hourly_odds_20260703T095031Z.parquet \
  --out output/wc2026-fast-graph \
  --fast-graph \
  --graph-lookback-days 30
```

Successful builds write `build_manifest.json` last. Treat that file as the
completion marker for a coherent output directory.

## Inspect Results

Search nodes:

```bash
python -m oddsgraph.cli search --out output/wc2026 --query "Brazil"
```

Show high-volume nodes:

```bash
python -m oddsgraph.cli nodes --out output/wc2026 --top 50
```

Show trusted structural or semantic logic edges:

```bash
python -m oddsgraph.cli edges --out output/wc2026 --edge-type implies --top 50
```

Show price-threshold relationships that are not accepted as logic:

```bash
python -m oddsgraph.cli price-edges --out output/wc2026 --edge-type implies --top 50
```

Show pricing or logic violations:

```bash
python -m oddsgraph.cli violations --out output/wc2026 --top 50
```

Explain a node:

```bash
python -m oddsgraph.cli explain --out output/wc2026 --node "<token id or unique text>"
```

Ask for a conditional probability row:

```bash
python -m oddsgraph.cli condition \
  --out output/wc2026 \
  --a 60941235333934119537308581623022145063589498358463811604437431757990716193139 \
  --b 69254358704504551873876012384649223770132435379419074198292590735170180021451
```

Summarize a completed build manifest:

```bash
python -m oddsgraph.cli benchmark-summary --out output/wc2026
```

## Documentation Map

- [docs/index.md](docs/index.md): handbook map and recommended reading order.
- [docs/cli.md](docs/cli.md): CLI commands, flags, query commands, and expected
  skipped-artifact errors.
- [docs/builds.md](docs/builds.md): build modes, optional inputs, manifest
  semantics, and artifact omission rules.
- [docs/artifacts.md](docs/artifacts.md): parquet artifact schemas and report
  reference.
- [docs/architecture.md](docs/architecture.md): build stages, major tables,
  edge lifecycle, coherence, evaluation, and performance hotspots.
- [docs/benchmarks.md](docs/benchmarks.md): benchmark methodology, dated local
  results, accepted/rejected optimizations, and summary command usage.

## Development Check

```bash
pytest -q
python -m oddsgraph.cli --help
```

The docs contract checks are part of `pytest -q`; there is no docs generator or
extra documentation dependency.

To run optional checks against an existing full WC2026 build:

```bash
pytest -q -m full_output
```
