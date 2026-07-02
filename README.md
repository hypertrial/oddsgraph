# oddsgraph

`oddsgraph` turns token-minute Polymarket odds into graph-ready parquet artifacts.
Each `clob_token_id` is treated as a probabilistic proposition node, then the
batch build emits price series, logical edges, conditional probabilities,
constraint rows, violation rows, and markdown reports.

This is a Python/DuckDB MVP for offline analysis. It is not a live ingest or
trading system.

## Requirements

- Python 3.11 or newer.
- DuckDB from the Python package dependency in `pyproject.toml`.
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

## Build Artifacts

Run the batch build:

```bash
python -m oddsgraph.cli build \
  --input wc2026_token_minutely_odds_20260702T070755Z.parquet \
  --out output/wc2026
```

Optional inputs:

```bash
python -m oddsgraph.cli build \
  --input wc2026_token_minutely_odds_20260702T070755Z.parquet \
  --quotes quotes.parquet \
  --resolutions resolutions.parquet \
  --taxonomy oddsgraph/taxonomies/wc2026.json \
  --out output/wc2026
```

For graph inspection runs where archival minute prices or global LP coherence
are not needed, skip the expensive optional artifacts explicitly:

```bash
python -m oddsgraph.cli build \
  --input wc2026_token_minutely_odds_20260702T070755Z.parquet \
  --out output/wc2026-fast \
  --skip-prices \
  --skip-coherence
```

On the local WC2026 file, the full build rewrites minute-level `prices.parquet`
and usually takes about 5 minutes on this machine (LP coherence adds per-event
solve time). The output directory is recreated in place for the DuckDB working
database and generated artifacts.

Latest local WC2026 run (`wc2026_token_minutely_odds_20260702T070755Z.parquet`):

| metric | value |
| --- | ---: |
| input rows | 53,827,798 |
| markets / tokens | 2,344 / 4,688 |
| candidate edges | 16,684 |
| logic edges | 12,886 |
| price edges | 12,137 |
| violations | 10 |
| incoherent events | 10 |
| runtime | 290s |

The artifact reference is in [docs/artifacts.md](docs/artifacts.md).
Successful builds also write `build_manifest.json` with taxonomy metadata,
effective calibrated thresholds, and summary stats.

## Inspect Results

Search nodes:

```bash
python -m oddsgraph.cli search --out output/wc2026 --query "Brazil win World Cup"
```

Show high-volume nodes:

```bash
python -m oddsgraph.cli nodes --out output/wc2026 --top 50
```

Show trusted structural or semantic logic edges:

```bash
python -m oddsgraph.cli edges --out output/wc2026 --edge-type implies --top 50
```

Supported edge filters are `complement`, `equivalent`, `implies`, and
`mutually_exclusive`. Omit `--edge-type` to list all edge types.

Show price-threshold relationships that are not accepted as logic:

```bash
python -m oddsgraph.cli price-edges --out output/wc2026 --edge-type implies --top 50
```

Explain a node, including its market sibling, touching edges, violations, and
conditional rows:

```bash
python -m oddsgraph.cli explain --out output/wc2026 --node "<token id or unique text>"
```

Explain a specific edge. Implications are directional; complement, equivalent,
and mutual-exclusion lookups also check the reverse stored order:

```bash
python -m oddsgraph.cli explain-edge \
  --out output/wc2026 \
  --src "<token id or unique text>" \
  --dst "<token id or unique text>" \
  --edge-type implies
```

Show pricing or logic violations:

```bash
python -m oddsgraph.cli violations --out output/wc2026 --top 50
```

Show per-event LP coherence and top repairs:

```bash
python -m oddsgraph.cli coherence --out output/wc2026 --top 20
```

Show resolution backtest metrics (requires build with `--resolutions`):

```bash
python -m oddsgraph.cli evaluate --out output/wc2026
```

Ask for a conditional probability row between two nodes. Each side can be a
full token id or search text that resolves to exactly one node:

```bash
python -m oddsgraph.cli condition \
  --out output/wc2026 \
  --a "Brazil reach the Round of 16" \
  --b "NOT(Will Brazil reach the Round of 16?)"
```

Generated markdown reports are written to `output/wc2026/reports/`, including
`coverage.md` for market-family and edge-basis coverage.

## Troubleshooting

- `DuckDB is required`: install the Python package with `python -m pip install -e ".[dev]"`.
- `Input parquet missing required columns`: compare the input with
  [wc2026_token_minutely_odds_20260702T070755Z.md](wc2026_token_minutely_odds_20260702T070755Z.md).
  The build expects uppercase `ODDS_TIMESTAMP` and `ODDS_TIMESTAMP_EPOCH`.
- `Input parquet failed validation`: fix the reported nulls, invalid prices,
  duplicate token timestamps, unstable token metadata, markets with fewer than two
  tokens, or markets without a complete current minute.
- Slow build: the MVP writes all minute-level prices. The WC2026 file has
  53,827,798 rows, so `prices.parquet` dominates runtime and disk I/O. Pair
  scoring uses a 30-day lookback window (`SCORING_LOOKBACK_DAYS` in
  `thresholds.py`) so year-long feeds do not materialize full pair-minute
  history. Use the full default build for archival/research output; use
  `--skip-prices` and/or `--skip-coherence` for faster graph inspection.
- `violations` returns rows: strict semantic edges can still have current prices
  that contradict the relationship. Inspect the row before treating it as data
  corruption.
- `condition` cannot resolve or reports an ambiguous query: run `search` first
  and pass exact `node_id` values.

## Development Check

```bash
pytest -q
python -m oddsgraph.cli --help
```

To run optional checks against an existing full WC2026 build:

```bash
pytest -q -m full_output
```
