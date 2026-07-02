# oddsgraph

`oddsgraph` turns token-minute Polymarket odds into graph-ready parquet artifacts.
Each `clob_token_id` is treated as a probabilistic proposition node, then the
batch build emits price series, logical edges, conditional probabilities,
constraint rows, violation rows, and markdown reports.

This is a Python/DuckDB MVP for offline analysis. It is not a live ingest or
trading system.

## Requirements

- Python 3.11 or newer.
- DuckDB, either as the Python package from `pyproject.toml` or as a `duckdb`
  CLI on `PATH`.
- A parquet input with the schema described in
  [wc2026_token_minutely_odds_20260702T070755Z.md](wc2026_token_minutely_odds_20260702T070755Z.md).

The current WC2026 parquet is a large local sample, about 621 MB. It is useful
for reproducing the MVP results, but large datasets should move to external
storage or a download step before this repo is treated as lightweight source
code.

## Setup

From the repo root:

```bash
python -m pip install -e ".[dev]"
```

If you do not install the Python `duckdb` package, make sure the DuckDB CLI is
available:

```bash
duckdb --version
```

## Build Artifacts

Run the batch build:

```bash
python -m oddsgraph.cli build \
  --input wc2026_token_minutely_odds_20260702T070755Z.parquet \
  --out output/wc2026
```

On the local WC2026 file, the full build rewrites a 53.8M-row `prices.parquet`
and usually takes about two minutes on this machine. The output directory is
recreated in place for the DuckDB working database and generated artifacts.

Latest local WC2026 run:

| Metric | Value |
| --- | ---: |
| Input rows | 53,827,798 |
| Markets | 2,344 |
| Tokens / nodes | 4,688 |
| Candidate edges | 13,750 |
| Logic edges | 9,987 |
| Constraint rows | 2,344 |
| Conditional rows | 21,070 |
| Violations | 0 |

The artifact reference is in [docs/artifacts.md](docs/artifacts.md).

## Inspect Results

Search nodes:

```bash
python -m oddsgraph.cli search --out output/wc2026 --query "Brazil win World Cup"
```

Show high-volume nodes:

```bash
python -m oddsgraph.cli nodes --out output/wc2026 --top 50
```

Show accepted logic edges:

```bash
python -m oddsgraph.cli edges --out output/wc2026 --edge-type implies --top 50
```

Supported edge filters are `complement`, `equivalent`, `implies`, and
`mutually_exclusive`. Omit `--edge-type` to list all edge types.

Show pricing or logic violations:

```bash
python -m oddsgraph.cli violations --out output/wc2026 --top 50
```

Ask for a conditional probability row between two nodes. Each side can be a
full token id or search text:

```bash
python -m oddsgraph.cli condition \
  --out output/wc2026 \
  --a "Brazil reach the Round of 16" \
  --b "NOT(Will Brazil reach the Round of 16?)"
```

Generated markdown reports are written to `output/wc2026/reports/`.

## Troubleshooting

- `DuckDB is required`: install the Python package with `python -m pip install -e ".[dev]"`
  or put the DuckDB CLI on `PATH`.
- `Input parquet missing required columns`: compare the input with
  [wc2026_token_minutely_odds_20260702T070755Z.md](wc2026_token_minutely_odds_20260702T070755Z.md).
  The build expects uppercase `ODDS_TIMESTAMP` and `ODDS_TIMESTAMP_EPOCH`.
- Slow build: the MVP writes all minute-level prices. The WC2026 file has
  53,827,798 rows, so `prices.parquet` dominates runtime and disk I/O.
- `violations` returns `No rows.`: that means no accepted relationship breached
  the configured v0.1.0 thresholds in the latest build.
- `condition` cannot resolve both nodes: run `search` first and pass the exact
  `node_id` values.

## Development Check

```bash
pytest -q
python -m oddsgraph.cli --help
```

To run optional checks against an existing full WC2026 build:

```bash
pytest -q -m full_output
```
