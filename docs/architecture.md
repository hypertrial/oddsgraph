# Architecture

`oddsgraph` is a sequential DuckDB build. The code keeps data in DuckDB tables
and views until final parquet exports, with Python used for orchestration,
taxonomy rules, calibration thresholds, and event-level LP coherence.

## Build Pipeline

Major stages:

1. Normalize input into `input_prices`.
2. Validate schema and row invariants.
3. Deduplicate token-minute prices into `token_minute_prices`.
4. Add devig, scoring prices, returns, and lookback filtering into enriched
   minute tables.
5. Build market completeness and market-minute aggregate stats.
6. Build `nodes_v` and `market_groups_v`.
7. Generate candidate edges from same-market structure, duplicate propositions,
   taxonomy rules, and price signals.
8. Score candidate pairs on aligned recent minute history.
9. Split accepted logic edges from price-only edges.
10. Add transitive derived implications.
11. Write constraint hyperedges from market groups.
12. Solve optional event-level LP coherence.
13. Write conditional probabilities and violations.
14. Write optional evaluation metrics when resolutions are provided.
15. Export parquet artifacts, markdown reports, validation results, and the
   manifest.

Each timed stage is recorded in `build_manifest.json` under `stage_timings`.
Critical intermediate tables are validated with lightweight column contracts
immediately after creation, so schema drift fails near the producing stage.

## Major Tables And Views

- `input_prices`: normalized source rows reused across validation and build SQL.
- `token_minute_prices`: one latest row per `(clob_token_id, odds_minute_epoch)`.
- `enriched_minute_prices`: deduped prices with devig, scoring, logit, returns,
  metadata, and current-minute markers.
- `scoring_minute_prices`: recent lookback subset used for pair scoring.
- `market_minute_sums`: shared market-minute sums and completeness flags.
- `nodes_v`: one row per token/proposition.
- `market_groups_v`: one row per market with token lists and market sum stats.
- `candidate_edges_v`: all candidate relationships before acceptance filters.
- `aligned_edges`: pair-minute history for candidate edge scoring.
- `logic_edges_v`: accepted semantic and structural graph edges.
- `price_edges_v`: price-threshold relationships not accepted as logic.
- `derived_edges_v`: transitive closure of accepted implication logic.
- `constraint_hyperedges_v`: binary complement and one-of-n market constraints.
- `coherence_v` and `coherence_repairs_v`: optional LP coherence output.
- `conditional_edges_v`: exact and bounded conditional probabilities.
- `violations_v`: persistence-aware contradictions and optional global
  incoherence rows.

## Edge Lifecycle

Candidate edges can come from five sources:

- `same_market`
- `exact_duplicate_same_event`
- `semantic_single_winner`
- `semantic_stage_progression`
- `price_same_event_slug`

Accepted logic edges are strict structural or semantic relationships. They use
edge bases such as `same_market`, `exact_duplicate`, `single_winner_family`, and
`stage_progression_rule`.

Price-only edges are useful signals but are not trusted as logic. They keep
their own artifact so downstream consumers can inspect them without mixing them
with structural graph facts.

Derived edges are transitive implications produced from accepted implication
logic. They carry a provenance `path` and `edge_basis = transitive`.

## Coherence And Evaluation

Coherence solves one LP per event: minimize total absolute adjustment from
observed current prices while satisfying accepted logic and market constraints.
The solver uses SciPy HiGHS with sparse constraint matrices. Trivial events that
already satisfy constraints can be written with zero incoherence distance
without invoking the solver.

When `--skip-coherence` or `--fast-graph` is used, downstream SQL receives empty
in-memory coherence tables so other graph artifacts can still be written. The
coherence parquet files are not written and are not listed in the manifest.

Evaluation is optional and only runs when `--resolutions` is provided. It writes
edge precision, violation follow-through, and Brier-style bucket metrics to
`evaluation.parquet` and `reports/evaluation.md`.

## Performance Hotspots

The largest full-build costs are usually:

- Full-history token-minute dedupe.
- Full-history price enrichment and `prices.parquet` export.
- Pair scoring on aligned recent minutes.
- Market-level completeness and sum aggregation.
- Event-level LP coherence setup on large event families.

`--fast-graph` reduces runtime by avoiding full-history `prices.parquet`, skipping
coherence output, and scoping historical graph stats to a lookback window while
preserving current prices and graph/query artifacts.
