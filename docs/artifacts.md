# oddsgraph Artifacts

The build writes parquet artifacts and markdown reports under the `--out`
directory. The graph node id is always `clob_token_id`, exposed as `node_id`.
`market_id` is a market container, not the graph node.

## Generated Parquet Files

### `nodes.parquet`

- Grain: one row per `clob_token_id`.
- Purpose: canonical proposition table for graph nodes.
- Important columns: `node_id`, `market_id`, `outcome_index`, `question`,
  `outcome_label`, `event_slug`, `canonical_proposition`, `proposition_type`,
  `first_seen_ts`, `last_seen_ts`, `active_minutes`, `current_price`,
  `mean_price`, `min_price`, `max_price`.
- Use it to search propositions, map token ids back to market text, and inspect
  current or historical price summaries.

Canonical proposition rules:

- `Yes`: `question`
- `No`: `NOT(question)`
- Other labels: `question :: outcome_label`

### `prices.parquet`

- Grain: one row per `(node_id, odds_timestamp_epoch)`.
- Purpose: cleaned minute-level price series.
- Important columns: `node_id`, `market_id`, `odds_timestamp`,
  `odds_timestamp_epoch`, `price`, `is_active`, `is_closed`,
  `market_volume_usd`, `logit_price`, `price_return_1m`.
- Use it for time-series analysis or to recompute custom pair scores.

### `market_groups.parquet`

- Grain: one row per `market_id`.
- Purpose: market-level grouping and binary sum diagnostics.
- Important columns: `market_id`, `event_slug`, `question`, `num_tokens`,
  `token_ids`, `outcome_labels`, `current_sum_price`, `mean_sum_price`.
- Use it to inspect same-market complements and the latest complete market sum.

### `candidate_edges.parquet`

- Grain: one row per candidate `(src_node_id, dst_node_id, candidate_type)`.
- Purpose: narrowed pair universe before scoring.
- Important columns: `src_node_id`, `dst_node_id`, `candidate_type`,
  `candidate_source`, `candidate_score`, source/destination market and event ids.
- Candidate sources: `same_market`, `same_event_slug`,
  `same_question_text_exact`.
- Use it to see what was eligible for scoring. The MVP does not generate global
  all-pairs candidates.

### `logic_edges.parquet`

- Grain: one accepted logical relationship.
- Purpose: main typed graph edge artifact.
- Important columns: `src_node_id`, `dst_node_id`, `edge_type`, `confidence`,
  `score`, `violation_score`, `overlap_minutes`, current and mean prices,
  source/destination market and event ids, `evidence`.
- Edge types: `complement`, `equivalent`, `implies`, `mutually_exclusive`.
- Use it as the primary graph edge table.

### `constraint_hyperedges.parquet`

- Grain: one market-level constraint.
- Purpose: market constraints, currently binary complement pairs.
- Important columns: `constraint_id`, `constraint_type`, `market_id`,
  `node_ids`, `current_sum_price`, `mean_sum_price`, `expected_sum_price`,
  `violation_score`, `confidence`.
- Use it to audit market-level sums without treating the market itself as a node.

### `conditional_edges.parquet`

- Grain: one conditional probability or bound for a candidate-related pair.
- Purpose: query `P(A | B)` when exact logic or Frechet bounds are available.
- Important columns: `a_node_id`, `b_node_id`, `p_a_given_b`, `lower_bound`,
  `upper_bound`, `method`, `confidence`, `evidence`.
- Methods: `exact_complement`, `exact_exclusion`, `exact_equivalence`,
  `exact_implication`, `exact_implication_reverse`, `bounded_frechet`.
- Use exact rows directly. For `bounded_frechet`, use `lower_bound` and
  `upper_bound`; `p_a_given_b` is intentionally null.

### `violations.parquet`

- Grain: one detected pricing or logic violation.
- Purpose: rank relationships whose current or mean prices breach thresholds.
- Important columns: `violation_id`, `violation_type`, node ids, market ids,
  `severity`, `current_gap`, `mean_gap`, `confidence`, `description`.
- Violation types: `complement_violation`, `equivalence_divergence`,
  `implication_violation`, `mutual_exclusion_violation`,
  `market_sum_violation`.
- Use it as the operator alert table. An empty file means no rows matched the
  configured thresholds.

## Reports

The build also writes markdown files under `reports/`:

- `summary.md`: input size, market/token counts, edge counts, violation count,
  runtime.
- `top_complement_violations.md`: largest same-market complement gaps.
- `strongest_implications.md`: highest-confidence implication edges.
- `strongest_exclusions.md`: highest-confidence mutual exclusions.
- `duplicate_candidates.md`: exact duplicate-question candidates.
- `conditional_examples.md`: sample conditional rows.

## Scoring Thresholds

Current v0.1.0 thresholds live in `oddsgraph/thresholds.py` and are rendered
into the build SQL:

- Cross-market candidates require both markets to have
  `MIN_MARKET_VOLUME_USD = 10000`, `MIN_ACTIVE_MINUTES = 1000`, matching
  `event_slug`, and `outcome_label = 'Yes'`.
- Cross-market accepted edges require `MIN_OVERLAP_MINUTES = 1000`.
- Equivalence accepts when `EQUIVALENCE_MEAN_ABS_DIFF_MAX = 0.02` and
  `EQUIVALENCE_CURRENT_ABS_DIFF_MAX = 0.03`.
- Implication uses `IMPLICATION_EPSILON = 0.01`,
  `IMPLICATION_VIOLATION_MEAN_MAX = 0.005`, and
  `IMPLICATION_CURRENT_SLACK = 0.02`.
- Mutual exclusion uses `EXCLUSION_EPSILON = 0.01`,
  `EXCLUSION_VIOLATION_MEAN_MAX = 0.005`, and
  `EXCLUSION_CURRENT_SUM_MAX = 1.02`.
- Complement candidates are always emitted for same-market token pairs.
  Confidence is lower when overlap is below `COMPLEMENT_LOW_OVERLAP_MINUTES = 10`.
- Complement violations use `COMPLEMENT_CURRENT_GAP_VIOLATION_MIN = 0.02` and
  `COMPLEMENT_MEAN_GAP_VIOLATION_MIN = 0.01`.

These thresholds favor precision over coverage in the MVP.
