# CLI Reference

Run commands from the repo root with `python -m oddsfox_graph.cli ...`.

## Build Commands

### `build`

Builds an output directory from token-hour odds parquet.

Required flags:

- `--input PATH`: source odds parquet.
- `--out DIR`: output directory. The build recreates generated files in this
  directory and writes `build_manifest.json` last.

Optional flags:

- `--quotes PATH`: optional bid/ask quote history. When provided, midpoint
  prices and half-spread noise floors are used for scoring.
- `--resolutions PATH`: optional resolved outcomes. When provided, the build
  writes `evaluation.parquet` and `reports/evaluation.md`.
- `--taxonomy PATH`: optional taxonomy JSON. Defaults to the bundled WC2026
  taxonomy.
- `--skip-prices`: do not write `prices.parquet`.
- `--skip-coherence`: do not write `coherence.parquet` or
  `coherence_repairs.parquet`.
- `--fast-graph`: opt into lookback-scoped graph mode. This implies skipped
  prices and skipped coherence output.
- `--graph-lookback-days N`: lookback window for `--fast-graph`. The value must
  be positive and can only be used with `--fast-graph`.
- `--current-max-age-hours N`: live-current freshness window. Defaults to `48`;
  markets whose latest complete bucket is older than this window, inactive, or
  closed are excluded before graph construction.
- `--allow-stale-current`: disable live-current eligibility for historical
  fixtures or backtests that deliberately need legacy stale-current behavior.

Examples:

```bash
python -m oddsfox_graph.cli build \
  --input "$ODDSFOX_DATA_DIR/exports/wc2026_graph_hourly.parquet" \
  --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026"
```

```bash
python -m oddsfox_graph.cli build \
  --input "$ODDSFOX_DATA_DIR/exports/wc2026_graph_hourly.parquet" \
  --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026-fast-graph" \
  --fast-graph \
  --graph-lookback-days 30
```

### `benchmark-summary`

Reads `build_manifest.json` from an existing output directory and prints
runtime, build options, graph counts, artifact count, and the slowest recorded
build stages.

```bash
python -m oddsfox_graph.cli benchmark-summary --out "$ODDSFOX_DATA_DIR/artifacts/manual/wc2026"
```

### `benchmark-compare`

Runs one full build and one fast graph build from the same input, writes
`benchmark_compare.json`, and prints the key runtime/count comparison. Runtime
deltas are informational only.

Flags:

- `--input PATH`: source odds parquet.
- `--out-root DIR`: parent directory for `full`, `fast_graph`, and
  `benchmark_compare.json`.
- `--graph-lookback-days N`, default `30`: fast graph lookback window.
- `--baseline-json PATH`: optional previous comparison JSON for numeric deltas.

```bash
python -m oddsfox_graph.cli benchmark-compare \
  --input "$ODDSFOX_DATA_DIR/exports/wc2026_graph_hourly.parquet" \
  --out-root "$ODDSFOX_DATA_DIR/artifacts/manual/benchmark_compare" \
  --graph-lookback-days 30
```

## Query Commands

All query commands read existing artifacts from `--out`.

### `nodes`

Lists nodes ordered by market volume and current price.

Flags:

- `--out DIR`
- `--top N`, default `50`

### `edges`

Lists accepted logic edges.

Flags:

- `--out DIR`
- `--edge-type TYPE`, optional. Supported values are `complement`,
  `equivalent`, `implies`, and `mutually_exclusive`.
- `--top N`, default `50`

### `price-edges`

Lists price-threshold relationships that were not promoted to logic.

Flags:

- `--out DIR`
- `--edge-type TYPE`, optional. Supported values are `complement`,
  `equivalent`, `implies`, and `mutually_exclusive`.
- `--top N`, default `50`

### `violations`

Lists persistence-aware pricing and logic violations.

Flags:

- `--out DIR`
- `--top N`, default `50`

### `coherence`

Lists per-event LP coherence summaries and largest repairs. Requires
`coherence.parquet` and `coherence_repairs.parquet`.

Flags:

- `--out DIR`
- `--top N`, default `50`

Expected skipped-artifact error:

```text
coherence.parquet was intentionally not generated; rebuild without --skip-coherence
```

### `evaluate`

Lists resolution backtest metrics. Requires a build created with
`--resolutions`.

Flags:

- `--out DIR`

Expected skipped-artifact error:

```text
evaluation.parquet was not generated; rebuild with --resolutions
```

### `condition`

Reads a conditional probability row for two nodes. Each side can be a full
`node_id` or search text that resolves to exactly one node.

Flags:

- `--out DIR`
- `--a TEXT`
- `--b TEXT`

### `explain`

Explains one node with its market siblings, touching logic edges, price-only
edges, violations, and conditional rows.

Flags:

- `--out DIR`
- `--node TEXT`

### `explain-edge`

Explains a specific edge. Implications are directional. Complement, equivalent,
and mutual-exclusion lookups also check the reverse stored order.

Flags:

- `--out DIR`
- `--src TEXT`
- `--dst TEXT`
- `--edge-type TYPE`, required. Supported values are `complement`,
  `equivalent`, `implies`, and `mutually_exclusive`.

### `search`

Searches `node_id`, question, canonical proposition, and outcome label text.

Flags:

- `--out DIR`
- `--query TEXT`
- `--top N`, default `20`
