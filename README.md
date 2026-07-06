# oddsfox-graph

`oddsfox-graph` turns token-hour Polymarket odds into graph-ready parquet
artifacts. Each `clob_token_id` becomes a proposition node, then the batch build
emits market groups, logical edges, price-only edges, derived implications,
conditional probabilities, constraint rows, violations, optional coherence and
evaluation artifacts, and markdown reports.

This is a Python/DuckDB tool for offline analysis. It is not a live ingest or
trading system.

## Requirements

- Python 3.11 or newer.
- DuckDB from the Python package dependency in `pyproject.toml`.
- A parquet input from
  `polymarket_wc2026_marts.polymarket_wc2026_graph_token_hourly_odds` or a
  legacy hourly/minutely OddsFox export.

The local WC2026 hourly parquet is a sample, about 41 MB. It is useful for
reproducing the project results, but generated outputs and large datasets should
stay outside source control.

## Get The Parquet

Use [hypertrial/oddsfox-pipeline](https://github.com/hypertrial/oddsfox-pipeline) to build and
export the source data. OddsFox documents the local pipeline in its
[quickstart](https://github.com/hypertrial/oddsfox-pipeline/blob/main/docs/quickstart.md).
For hosted WC2026 graph builds, export
`polymarket_wc2026_marts.polymarket_wc2026_graph_token_hourly_odds`:

```bash
export ODDSFOX_DATA_DIR="${ODDSFOX_DATA_DIR:-/Volumes/Mac SSD/hypertrial_trilemma/hypertrial/OddsFox/.runtime}"
mkdir -p "$ODDSFOX_DATA_DIR/exports"
uv run python scripts/export_polymarket_wc2026_graph_hourly_odds.py \
  --snapshot-copy \
  --output "$ODDSFOX_DATA_DIR/exports/wc2026_graph_hourly.parquet"
```

This graph export carries both Yes/No tokens and dbt-clean team, stage,
progression-token, and opposite-token semantics. Legacy OddsFox hourly/minutely
exports remain supported for audits and backtests; regex/taxonomy parsing is
used only when semantic columns are absent.

## Setup

From the repo root:

```bash
python -m pip install -e ".[dev]"
```

## Build Artifacts

Run a full build when you want the complete artifact set:

```bash
python -m oddsfox_graph.cli build \
  --input "$ODDSFOX_DATA_DIR/exports/wc2026_graph_hourly.parquet" \
  --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026"
```

Run fast graph mode when you want graph/query artifacts quickly and can accept
lookback-scoped historical node and market statistics:

```bash
python -m oddsfox_graph.cli build \
  --input "$ODDSFOX_DATA_DIR/exports/wc2026_graph_hourly.parquet" \
  --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026-fast-graph" \
  --fast-graph \
  --graph-lookback-days 30
```

Successful builds write `build_manifest.json` last. Treat that file as the
completion marker for a coherent output directory.

WC2026 builds also write `knockout_artifacts.json` and `graph_snapshot.json` for
`oddsfox-live`. The knockout artifact contains stages, teams, stage-market asset
IDs, bracket slots, baseline market-ratio conditional probabilities, and hourly
probability history. The graph snapshot is compact JSON for the hosted logical
graph API.

## Inspect Results

Search nodes:

```bash
python -m oddsfox_graph.cli search --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026" --query "Brazil"
```

Show high-volume nodes:

```bash
python -m oddsfox_graph.cli nodes --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026" --top 50
```

Show trusted structural or semantic logic edges:

```bash
python -m oddsfox_graph.cli edges --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026" --edge-type implies --top 50
```

Show price-threshold relationships that are not accepted as logic:

```bash
python -m oddsfox_graph.cli price-edges --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026" --edge-type implies --top 50
```

Show pricing or logic violations:

```bash
python -m oddsfox_graph.cli violations --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026" --top 50
```

Explain a node:

```bash
python -m oddsfox_graph.cli explain --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026" --node "<token id or unique text>"
```

Ask for a conditional probability row:

```bash
python -m oddsfox_graph.cli condition \
  --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026" \
  --a 60941235333934119537308581623022145063589498358463811604437431757990716193139 \
  --b 69254358704504551873876012384649223770132435379419074198292590735170180021451
```

Summarize a completed build manifest:

```bash
python -m oddsfox_graph.cli benchmark-summary --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026"
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
python -m oddsfox_graph.cli --help
```

The docs contract checks are part of `pytest -q`; there is no docs generator or
extra documentation dependency.

To run optional checks against an existing full WC2026 build:

```bash
pytest -q -m full_output
```
