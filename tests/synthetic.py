from __future__ import annotations

from pathlib import Path
from typing import Any

from oddsgraph import thresholds as T
from oddsgraph.queries import DuckDB, q
from oddsgraph.sql import values_rows_sql


MARKET_COLUMNS = [
    "market_id",
    "question",
    "event_slug",
    "yes_base",
    "yes_current",
    "no_base",
    "no_current",
    "volume",
    "minute_count",
    "start_epoch",
]

MINI_WC2026_MARKET_COLUMNS = [
    "market_id",
    "question",
    "event_slug",
    "yes_token",
    "no_token",
    "yes_price",
    "no_price",
    "volume",
    "minute_count",
    "start_epoch",
]

HOURLY_MARKET_COLUMNS = [
    "market_id",
    "question",
    "event_slug",
    "yes_price",
    "no_price",
    "volume",
    "bucket_count",
    "start_epoch",
]

STALE_CURRENT_HOURLY_MARKET_COLUMNS = [
    "market_id",
    "question",
    "event_slug",
    "yes_price",
    "no_price",
    "volume",
    "bucket_count",
    "start_epoch",
    "is_active",
    "is_closed",
]


def _values(rows: list[tuple[Any, ...]], columns: list[str]) -> str:
    return values_rows_sql([dict(zip(columns, row, strict=True)) for row in rows], columns)


def write_synthetic_input(path: Path) -> None:
    markets = [
        ("comp", "Will Complement pass?", "comp-event", 0.42, 0.42, 0.58, 0.58, 20_000.0, 1000, 0),
        ("bad", "Will Bad Sum pass?", "bad-event", 0.70, 0.70, 0.70, 0.70, 20_000.0, 1000, 10_000),
        ("eq_a", "Will Equivalent A happen?", "eq-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 20_000),
        ("eq_b", "Will Equivalent B happen?", "eq-event", 0.56, 0.56, 0.44, 0.44, 20_000.0, 1000, 20_000),
        ("eq_shift_a", "Will Shift A happen?", "eq-shift-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 30_000),
        ("eq_shift_b", "Will Shift B happen?", "eq-shift-event", 0.60, 0.60, 0.40, 0.40, 20_000.0, 1000, 30_000),
        ("eq_spike_a", "Will Spike A happen?", "eq-spike-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 40_000),
        ("eq_spike_b", "Will Spike B happen?", "eq-spike-event", 0.56, 0.70, 0.44, 0.30, 20_000.0, 1000, 40_000),
        ("imp_a", "Will Specific outcome happen?", "imp-event", 0.70, 0.70, 0.30, 0.30, 20_000.0, 1000, 50_000),
        ("imp_b", "Will Broader outcome happen?", "imp-event", 0.90, 0.90, 0.10, 0.10, 20_000.0, 1000, 50_000),
        ("imp_mean_bad_a", "Will Mean Bad A happen?", "imp-mean-bad-event", 0.80, 0.80, 0.20, 0.20, 20_000.0, 1000, 60_000),
        ("imp_mean_bad_b", "Will Mean Bad B happen?", "imp-mean-bad-event", 0.70, 0.70, 0.30, 0.30, 20_000.0, 1000, 60_000),
        ("imp_current_bad_a", "Will Current Bad A happen?", "imp-current-bad-event", 0.70, 0.95, 0.30, 0.05, 20_000.0, 1000, 70_000),
        ("imp_current_bad_b", "Will Current Bad B happen?", "imp-current-bad-event", 0.90, 0.90, 0.10, 0.10, 20_000.0, 1000, 70_000),
        ("excl_a", "Will Exclusion A happen?", "excl-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 80_000),
        ("excl_b", "Will Exclusion B happen?", "excl-event", 0.45, 0.45, 0.55, 0.55, 20_000.0, 1000, 80_000),
        ("excl_mean_bad_a", "Will Exclusion Mean Bad A happen?", "excl-mean-bad-event", 0.70, 0.70, 0.30, 0.30, 20_000.0, 1000, 90_000),
        ("excl_mean_bad_b", "Will Exclusion Mean Bad B happen?", "excl-mean-bad-event", 0.40, 0.40, 0.60, 0.60, 20_000.0, 1000, 90_000),
        ("excl_current_bad_a", "Will Exclusion Current Bad A happen?", "excl-current-bad-event", 0.55, 0.70, 0.45, 0.30, 20_000.0, 1000, 100_000),
        ("excl_current_bad_b", "Will Exclusion Current Bad B happen?", "excl-current-bad-event", 0.45, 0.45, 0.55, 0.55, 20_000.0, 1000, 100_000),
        ("low_volume_a", "Will Low Volume A happen?", "low-volume-event", 0.55, 0.55, 0.45, 0.45, T.MIN_MARKET_VOLUME_USD - 1, 1000, 110_000),
        ("low_volume_b", "Will Low Volume B happen?", "low-volume-event", 0.56, 0.56, 0.44, 0.44, T.MIN_MARKET_VOLUME_USD - 1, 1000, 110_000),
        ("low_active_a", "Will Low Active A happen?", "low-active-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, T.MIN_ACTIVE_MINUTES - 1, 120_000),
        ("low_active_b", "Will Low Active B happen?", "low-active-event", 0.56, 0.56, 0.44, 0.44, 20_000.0, T.MIN_ACTIVE_MINUTES - 1, 120_000),
        ("low_overlap_a", "Will Low Overlap A happen?", "low-overlap-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 130_000),
        ("low_overlap_b", "Will Low Overlap B happen?", "low-overlap-event", 0.56, 0.56, 0.44, 0.44, 20_000.0, 1000, 130_950),
        ("diff_event_a", "Will Different Event A happen?", "diff-event-a", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 140_000),
        ("diff_event_b", "Will Different Event B happen?", "diff-event-b", 0.56, 0.56, 0.44, 0.44, 20_000.0, 1000, 140_000),
        ("dup_same_a", "Will Duplicate Semantic happen?", "dup-sem-event", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 150_000),
        ("dup_same_b", "Will Duplicate Semantic happen?", "dup-sem-event", 0.56, 0.56, 0.44, 0.44, 20_000.0, 1000, 150_000),
        ("dup_cross_a", "Will Cross Event Duplicate happen?", "dup-cross-a", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 160_000),
        ("dup_cross_b", "Will Cross Event Duplicate happen?", "dup-cross-b", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 160_000),
        ("winner_alpha", "Will Alpha win the 2026 FIFA World Cup?", "world-cup-winner", 0.35, 0.35, 0.65, 0.65, 20_000.0, 1000, 170_000),
        ("winner_beta", "Will Beta win the 2026 FIFA World Cup?", "world-cup-winner", 0.25, 0.25, 0.75, 0.75, 20_000.0, 1000, 170_000),
        ("alpha_final", "Will Alpha reach the 2026 FIFA World Cup final?", "world-cup-nation-to-reach-final", 0.55, 0.55, 0.45, 0.45, 20_000.0, 1000, 180_000),
        ("alpha_semis", "Will Alpha reach the Semifinals at the 2026 FIFA World Cup?", "world-cup-nation-to-reach-semifinals", 0.75, 0.75, 0.25, 0.25, 20_000.0, 1000, 190_000),
    ]
    db = DuckDB(path.with_suffix(".duckdb"))
    try:
        db.execute(
            f"""
            CREATE TABLE fixture AS
            WITH market_defs(
                market_id,
                question,
                event_slug,
                yes_base,
                yes_current,
                no_base,
                no_current,
                volume,
                minute_count,
                start_epoch
            ) AS (
                VALUES
                {_values(markets, MARKET_COLUMNS)}
            ),
            minute AS (
                SELECT range::BIGINT AS i
                FROM range(1001)
            ),
            binary_rows AS (
                SELECT
                    market_id,
                    outcome_index,
                    market_id || ':' || outcome_label AS clob_token_id,
                    question,
                    outcome_label,
                    event_slug,
                    true AS is_active,
                    false AS is_closed,
                    volume AS market_volume_usd,
                    to_timestamp(start_epoch + i * 60) AS ODDS_TIMESTAMP,
                    (start_epoch + i * 60)::BIGINT AS ODDS_TIMESTAMP_EPOCH,
                    CASE outcome_label
                        WHEN 'Yes' THEN CASE WHEN i = minute_count - 1 THEN yes_current ELSE yes_base END
                        ELSE CASE WHEN i = minute_count - 1 THEN no_current ELSE no_base END
                    END AS price
                FROM market_defs
                JOIN minute ON i < minute_count
                CROSS JOIN (VALUES (0, 'Yes'), (1, 'No')) AS o(outcome_index, outcome_label)
            ),
            named_rows AS (
                SELECT
                    'named' AS market_id,
                    outcome_index,
                    'named:' || outcome_label AS clob_token_id,
                    'Top goalscorer?' AS question,
                    outcome_label,
                    'named-event' AS event_slug,
                    true AS is_active,
                    false AS is_closed,
                    1.0 AS market_volume_usd,
                    to_timestamp(200000 + i * 60) AS ODDS_TIMESTAMP,
                    (200000 + i * 60)::BIGINT AS ODDS_TIMESTAMP_EPOCH,
                    CASE outcome_label WHEN 'Messi' THEN 0.55 ELSE 0.45 END AS price
                FROM (SELECT * FROM minute LIMIT 3)
                CROSS JOIN (VALUES (0, 'Messi'), (1, 'Ronaldo')) AS o(outcome_index, outcome_label)
            ),
            nary_rows AS (
                SELECT
                    'golden_boot' AS market_id,
                    outcome_index,
                    'golden_boot:' || outcome_label AS clob_token_id,
                    'Who wins Golden Boot?' AS question,
                    outcome_label,
                    'world-cup-golden-boot-winner' AS event_slug,
                    true AS is_active,
                    false AS is_closed,
                    20_000.0 AS market_volume_usd,
                    to_timestamp(220000 + i * 60) AS ODDS_TIMESTAMP,
                    (220000 + i * 60)::BIGINT AS ODDS_TIMESTAMP_EPOCH,
                    CASE outcome_label
                        WHEN 'Alpha' THEN 0.34
                        WHEN 'Beta' THEN 0.33
                        ELSE 0.33
                    END AS price
                FROM minute
                CROSS JOIN (VALUES (0, 'Alpha'), (1, 'Beta'), (2, 'Gamma')) AS o(outcome_index, outcome_label)
                WHERE i < 1000
            ),
            stale_rows AS (
                SELECT 'stale', 0, 'stale:Yes', 'Will stale pass?', 'Yes', 'stale-event', true, false, 1.0,
                    to_timestamp(210000), 210000::BIGINT, 0.2
                UNION ALL SELECT 'stale', 1, 'stale:No', 'Will stale pass?', 'No', 'stale-event', true, false, 1.0,
                    to_timestamp(210000), 210000::BIGINT, 0.8
                UNION ALL SELECT 'stale', 0, 'stale:Yes', 'Will stale pass?', 'Yes', 'stale-event', true, false, 1.0,
                    to_timestamp(210061), 210061::BIGINT, 0.9
            )
            SELECT * FROM binary_rows
            UNION ALL SELECT * FROM named_rows
            UNION ALL SELECT * FROM nary_rows
            UNION ALL SELECT * FROM stale_rows;

            COPY fixture TO '{q(path)}' (FORMAT PARQUET);
            """
        )
    finally:
        db.close()


def write_hourly_synthetic_input(path: Path) -> None:
    markets = [
        (
            "hourly_eq_a",
            "Will Hourly Equivalent A happen?",
            "hourly-price-event",
            0.55,
            0.45,
            20_000.0,
            24,
            0,
        ),
        (
            "hourly_eq_b",
            "Will Hourly Equivalent B happen?",
            "hourly-price-event",
            0.56,
            0.44,
            20_000.0,
            24,
            0,
        ),
        (
            "hourly_low_a",
            "Will Hourly Low A happen?",
            "hourly-low-support-event",
            0.55,
            0.45,
            20_000.0,
            16,
            100_000,
        ),
        (
            "hourly_low_b",
            "Will Hourly Low B happen?",
            "hourly-low-support-event",
            0.56,
            0.44,
            20_000.0,
            16,
            100_000,
        ),
        (
            "bosnia_r16",
            "Will Bosnia-Herzegovina reach the Round of 16 at the 2026 FIFA World Cup?",
            "world-cup-nation-to-reach-round-of-16",
            0.60,
            0.40,
            20_000.0,
            24,
            200_000,
        ),
        (
            "bosnia_final",
            "Will Bosnia and Herzegovina reach the 2026 FIFA World Cup final?",
            "world-cup-nation-to-reach-final",
            0.30,
            0.70,
            20_000.0,
            24,
            200_000,
        ),
        (
            "congo_qf",
            "Will Congo DR reach the Quarterfinals at the 2026 FIFA World Cup?",
            "world-cup-nation-to-reach-quarterfinals",
            0.45,
            0.55,
            20_000.0,
            24,
            300_000,
        ),
        (
            "congo_semis",
            "Will DR Congo reach the Semifinals at the 2026 FIFA World Cup?",
            "world-cup-nation-to-reach-semifinals",
            0.25,
            0.75,
            20_000.0,
            24,
            300_000,
        ),
        (
            "curacao_qf",
            "Will Curaçao reach the Quarterfinals at the 2026 FIFA World Cup?",
            "world-cup-nation-to-reach-quarterfinals",
            0.42,
            0.58,
            20_000.0,
            24,
            400_000,
        ),
        (
            "curacao_semis",
            "Will Curacao reach the Semifinals at the 2026 FIFA World Cup?",
            "world-cup-nation-to-reach-semifinals",
            0.22,
            0.78,
            20_000.0,
            24,
            400_000,
        ),
    ]
    db = DuckDB(path.with_suffix(".duckdb"))
    try:
        db.execute(
            f"""
            CREATE TABLE hourly_fixture AS
            WITH market_defs(
                market_id,
                question,
                event_slug,
                yes_price,
                no_price,
                volume,
                bucket_count,
                start_epoch
            ) AS (
                VALUES
                {_values(markets, HOURLY_MARKET_COLUMNS)}
            ),
            hour AS (
                SELECT range::BIGINT AS i
                FROM range(24)
            )
            SELECT
                market_id,
                outcome_index,
                market_id || ':' || outcome_label AS clob_token_id,
                question,
                outcome_label,
                event_slug,
                true AS is_active,
                false AS is_closed,
                volume AS market_volume_usd,
                to_timestamp(start_epoch + i * 3600) AS odds_hour_utc,
                (start_epoch + i * 3600)::BIGINT AS odds_hour_epoch,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS open_price,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS high_price,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS low_price,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS close_price,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS avg_price,
                1::BIGINT AS observed_points,
                (start_epoch + i * 3600)::BIGINT AS first_timestamp,
                to_timestamp(start_epoch + i * 3600) AS first_observed_at,
                (start_epoch + i * 3600)::BIGINT AS last_timestamp,
                to_timestamp(start_epoch + i * 3600) AS last_observed_at
            FROM market_defs
            JOIN hour ON i < bucket_count
            CROSS JOIN (VALUES (0, 'Yes'), (1, 'No')) AS o(outcome_index, outcome_label);

            COPY hourly_fixture TO '{q(path)}' (FORMAT PARQUET);
            """
        )
    finally:
        db.close()


def write_stale_current_hourly_input(path: Path) -> None:
    markets = [
        (
            "live_r16",
            "Will Live reach the Round of 16 at the 2026 FIFA World Cup?",
            "live-round-16",
            0.60,
            0.40,
            20_000.0,
            3,
            98 * 3600,
            True,
            False,
        ),
        (
            "live_qf",
            "Will Live reach the Quarterfinals at the 2026 FIFA World Cup?",
            "live-quarterfinals",
            0.40,
            0.60,
            20_000.0,
            3,
            98 * 3600,
            True,
            False,
        ),
        (
            "closed_r16",
            "Will Closed reach the Round of 16 at the 2026 FIFA World Cup?",
            "closed-round-16",
            0.02,
            0.98,
            20_000.0,
            3,
            98 * 3600,
            True,
            True,
        ),
        (
            "closed_qf",
            "Will Closed reach the Quarterfinals at the 2026 FIFA World Cup?",
            "closed-quarterfinals",
            0.01,
            0.99,
            20_000.0,
            3,
            98 * 3600,
            True,
            True,
        ),
        (
            "stale_r16",
            "Will Stale reach the Round of 16 at the 2026 FIFA World Cup?",
            "stale-round-16",
            0.55,
            0.45,
            20_000.0,
            3,
            0,
            True,
            False,
        ),
        (
            "stale_qf",
            "Will Stale reach the Quarterfinals at the 2026 FIFA World Cup?",
            "stale-quarterfinals",
            0.30,
            0.70,
            20_000.0,
            3,
            0,
            True,
            False,
        ),
    ]
    db = DuckDB(path.with_suffix(".duckdb"))
    try:
        db.execute(
            f"""
            CREATE TABLE stale_current_hourly_fixture AS
            WITH market_defs(
                market_id,
                question,
                event_slug,
                yes_price,
                no_price,
                volume,
                bucket_count,
                start_epoch,
                is_active,
                is_closed
            ) AS (
                VALUES
                {_values(markets, STALE_CURRENT_HOURLY_MARKET_COLUMNS)}
            ),
            hour AS (
                SELECT range::BIGINT AS i
                FROM range(3)
            )
            SELECT
                market_id,
                outcome_index,
                market_id || ':' || outcome_label AS clob_token_id,
                question,
                outcome_label,
                event_slug,
                is_active,
                is_closed,
                volume AS market_volume_usd,
                to_timestamp(start_epoch + i * 3600) AS odds_hour_utc,
                (start_epoch + i * 3600)::BIGINT AS odds_hour_epoch,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS open_price,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS high_price,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS low_price,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS close_price,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS avg_price,
                1::BIGINT AS observed_points,
                (start_epoch + i * 3600)::BIGINT AS first_timestamp,
                to_timestamp(start_epoch + i * 3600) AS first_observed_at,
                (start_epoch + i * 3600)::BIGINT AS last_timestamp,
                to_timestamp(start_epoch + i * 3600) AS last_observed_at
            FROM market_defs
            JOIN hour ON i < bucket_count
            CROSS JOIN (VALUES (0, 'Yes'), (1, 'No')) AS o(outcome_index, outcome_label);

            COPY stale_current_hourly_fixture TO '{q(path)}' (FORMAT PARQUET);
            """
        )
    finally:
        db.close()


def write_synthetic_resolutions(path: Path) -> None:
    rows = [
        {"clob_token_id": "comp:Yes", "market_id": "comp", "outcome_label": "Yes", "payout": 1.0, "resolved_epoch": 300000},
        {"clob_token_id": "comp:No", "market_id": "comp", "outcome_label": "No", "payout": 0.0, "resolved_epoch": 300000},
        {"clob_token_id": "winner_alpha:Yes", "market_id": "winner_alpha", "outcome_label": "Yes", "payout": 0.0, "resolved_epoch": 300000},
        {"clob_token_id": "alpha_final:Yes", "market_id": "alpha_final", "outcome_label": "Yes", "payout": 0.0, "resolved_epoch": 300000},
    ]
    columns = ["clob_token_id", "market_id", "outcome_label", "payout", "resolved_epoch"]
    db = DuckDB(path.with_suffix(".duckdb"))
    try:
        db.execute(f"""
            COPY (
                SELECT
                    clob_token_id,
                    market_id,
                    outcome_label,
                    payout,
                    to_timestamp(resolved_epoch) AS resolved_at
                FROM (VALUES {values_rows_sql(rows, columns)})
                    AS t(clob_token_id, market_id, outcome_label, payout, resolved_epoch)
            ) TO '{q(path)}' (FORMAT PARQUET);
        """)
    finally:
        db.close()


def write_mini_wc2026_oracle_input(path: Path) -> None:
    markets: list[tuple[Any, ...]] = []

    def add_market(
        market_id: str,
        question: str,
        event_slug: str,
        yes_token: str,
        no_token: str,
        yes_price: float,
        *,
        start_epoch: int,
    ) -> None:
        markets.append((
            market_id,
            question,
            event_slug,
            yes_token,
            no_token,
            yes_price,
            1.0 - yes_price,
            20_000.0,
            1000,
            start_epoch,
        ))

    add_market(
        "mini_brazil_round_16",
        "Will Brazil reach the Round of 16 at the 2026 FIFA World Cup?",
        "mini-brazil-round-16",
        "60941235333934119537308581623022145063589498358463811604437431757990716193139",
        "69254358704504551873876012384649223770132435379419074198292590735170180021451",
        0.42,
        start_epoch=0,
    )
    add_market(
        "mini_announcer_source",
        "Will the opening match announcer mention the host city before kickoff?",
        "mini-unrelated-announcer-event",
        "43210016944742792301737134223300418595113462948362079532359960011115262422579",
        "mini_announcer_source:no",
        0.41,
        start_epoch=100_000,
    )
    add_market(
        "mini_announcer_destination",
        "Will a halftime broadcast graphic show attendance above sixty thousand?",
        "mini-unrelated-announcer-event",
        "27853601490370072812708927706802149718970975520996501176000797916279903304531",
        "mini_announcer_destination:no",
        0.62,
        start_epoch=100_000,
    )

    price_only_pairs = [
        (
            "91399166209216163431231173062786395215620442056888296437823451282732143924332",
            "66265680142177294497572235248200066124169304713332831132816781431445413907569",
        ),
        (
            "90538013438399246674125939147272424357773921253199632436930218305581040235987",
            "23542782083949026234898323432000742558288032327930681121040136746492993951914",
        ),
        (
            "33747305042007778221968790541070114008811587676172030120559423448386310500957",
            "97239126062673310243763617236644392945530356142765650402171508075574679292913",
        ),
    ]
    for idx, (src_token, dst_token) in enumerate(price_only_pairs):
        event_slug = f"mini-price-only-implication-{idx}"
        start_epoch = 200_000 + idx * 10_000
        add_market(
            f"mini_price_src_{idx}",
            f"Will mini price source {idx} happen?",
            event_slug,
            src_token,
            f"mini_price_src_{idx}:no",
            0.30,
            start_epoch=start_epoch,
        )
        add_market(
            f"mini_price_dst_{idx}",
            f"Will mini price destination {idx} happen?",
            event_slug,
            dst_token,
            f"mini_price_dst_{idx}:no",
            0.70,
            start_epoch=start_epoch,
        )

    db = DuckDB(path.with_suffix(".duckdb"))
    try:
        db.execute(
            f"""
            CREATE TABLE mini_wc2026_fixture AS
            WITH market_defs(
                market_id,
                question,
                event_slug,
                yes_token,
                no_token,
                yes_price,
                no_price,
                volume,
                minute_count,
                start_epoch
            ) AS (
                VALUES
                {_values(markets, MINI_WC2026_MARKET_COLUMNS)}
            ),
            minute AS (
                SELECT range::BIGINT AS i
                FROM range(1000)
            )
            SELECT
                market_id,
                outcome_index,
                CASE outcome_label WHEN 'Yes' THEN yes_token ELSE no_token END AS clob_token_id,
                question,
                outcome_label,
                event_slug,
                true AS is_active,
                false AS is_closed,
                volume AS market_volume_usd,
                to_timestamp(start_epoch + i * 60) AS ODDS_TIMESTAMP,
                (start_epoch + i * 60)::BIGINT AS ODDS_TIMESTAMP_EPOCH,
                CASE outcome_label WHEN 'Yes' THEN yes_price ELSE no_price END AS price
            FROM market_defs
            JOIN minute ON i < minute_count
            CROSS JOIN (VALUES (0, 'Yes'), (1, 'No')) AS o(outcome_index, outcome_label);

            COPY mini_wc2026_fixture TO '{q(path)}' (FORMAT PARQUET);
            """
        )
    finally:
        db.close()
