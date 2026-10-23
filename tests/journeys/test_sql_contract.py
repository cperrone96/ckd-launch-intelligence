from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from ckd_intelligence.journeys.synpuf import build_journey_output
from journeys.provenance import load_verified_synpuf_fixture

FIXTURE = Path(__file__).parents[2] / "data" / "fixtures" / "synpuf_journeys.csv"
SQL = (Path(__file__).parents[2] / "sql" / "marts" / "mart_synpuf_journeys.sql").read_text()
EVENT_COLUMNS = [
    "synthetic_id",
    "claim_id",
    "source_release",
    "event_date",
    "event_through_date",
    "claim_type",
    "diagnosis_code",
    "event_kind",
    "event_order",
    "is_ckd_signal",
    "is_target_event",
    "is_persistence_event",
    "index_date",
    "target_date",
    "persistence_date",
    "follow_up_end",
    "evidence_type",
]
SUMMARY_COLUMNS = [
    "synthetic_id",
    "index_date",
    "target_date",
    "persistence_date",
    "observation_end",
    "duration_days",
    "event_observed",
    "censoring_reason",
    "has_target",
    "evidence_type",
]
SURVIVAL_COLUMNS = [
    "time",
    "at_risk",
    "events",
    "censored",
    "survival",
    "greenwood_variance",
    "ci_low",
    "ci_high",
    "evidence_type",
]


def _claims() -> pd.DataFrame:
    return load_verified_synpuf_fixture()


def _adversarial_ties() -> pd.DataFrame:
    base = _claims().iloc[0:0].copy()
    rows = [
        ("TIE1", "A", "2009-01-01", "4019"),
        ("TIE1", "B", "2009-02-01", "5853"),
        ("TIE1", "D", "2009-05-02", "5853"),
        ("TIE1", "E", "2009-05-02", "4019"),
        ("TIE1", "F", "2009-05-02", "5853"),
    ]
    for beneficiary_id, claim_id, service_date, diagnosis in rows:
        base.loc[len(base)] = {
            "source_release": "2008-2010",
            "beneficiary_id": beneficiary_id,
            "claim_id": claim_id,
            "claim_type": "outpatient",
            "service_from_date": service_date,
            "service_through_date": service_date,
            "diagnosis_code": diagnosis,
            "provider_id": "PTIE",
            "payment_amount_usd": 1.0,
            "year": 2009,
            "evidence_type": "public_synthetic",
        }
    return base


def _spanning_early_claim() -> pd.DataFrame:
    base = _claims().iloc[0:0].copy()
    rows = [
        ("SPAN", "SPAN-1", "2009-01-01", "2010-02-01", "4019", "inpatient"),
        ("SPAN", "SPAN-2", "2009-12-01", "2009-12-01", "5853", "outpatient"),
    ]
    for beneficiary_id, claim_id, event_date, through_date, diagnosis, claim_type in rows:
        base.loc[len(base)] = {
            "source_release": "2008-2010",
            "beneficiary_id": beneficiary_id,
            "claim_id": claim_id,
            "claim_type": claim_type,
            "service_from_date": event_date,
            "service_through_date": through_date,
            "diagnosis_code": diagnosis,
            "provider_id": "PSPAN",
            "payment_amount_usd": 1.0,
            "year": 2009,
            "evidence_type": "public_synthetic",
        }
    return base


def _spanning_only_claim() -> pd.DataFrame:
    base = _claims().iloc[0:0].copy()
    base.loc[0] = {
        "source_release": "2008-2010",
        "beneficiary_id": "SPAN-ONLY",
        "claim_id": "SPAN-ONLY-1",
        "claim_type": "inpatient",
        "service_from_date": "2009-01-01",
        "service_through_date": "2010-02-01",
        "diagnosis_code": "5853",
        "provider_id": "PSONLY",
        "payment_amount_usd": 1.0,
        "year": 2009,
        "evidence_type": "public_synthetic",
    }
    return base


def _custom(rows: list[tuple[str, str, str, str, str]]) -> pd.DataFrame:
    """Build fixture-shaped claims from (beneficiary, claim, from, through, dx) tuples."""

    base = _claims().iloc[0:0].copy()
    for beneficiary_id, claim_id, from_date, through_date, diagnosis in rows:
        base.loc[len(base)] = {
            "source_release": "2008-2010",
            "beneficiary_id": beneficiary_id,
            "claim_id": claim_id,
            "claim_type": "outpatient",
            "service_from_date": from_date,
            "service_through_date": through_date,
            "diagnosis_code": diagnosis,
            "provider_id": "PCUSTOM",
            "payment_amount_usd": 1.0,
            "year": int(from_date[:4]),
            "evidence_type": "public_synthetic",
        }
    return base


def _spanning_claim_hides_later_claim() -> pd.DataFrame:
    # Regression: Python used to drop C3 after an early cutoff from C1.
    return _custom(
        [
            ("R", "C1", "2008-01-01", "2009-06-01", "4019"),
            ("R", "C2", "2008-03-01", "2008-03-01", "5853"),
            ("R", "C3", "2009-02-15", "2009-02-15", "5853"),
        ]
    )


def _late_target_no_target_and_window_edges() -> pd.DataFrame:
    return pd.concat(
        [
            _claims(),
            _custom(
                [
                    ("LATE", "LATE-1", "2008-01-01", "2008-01-01", "4019"),
                    ("LATE", "LATE-2", "2010-06-01", "2010-06-01", "5853"),
                    ("LATE", "LATE-3", "2010-10-01", "2010-10-01", "5853"),
                    ("NONE", "NONE-1", "2008-02-01", "2008-02-01", "4019"),
                    ("EDGE", "E1", "2008-03-01", "2008-03-01", "5853"),
                    ("EDGE", "E2", "2009-02-28", "2009-02-28", "5853"),
                    ("OUT", "O1", "2008-03-01", "2008-03-01", "5853"),
                    ("OUT", "O2", "2009-03-01", "2009-03-01", "5853"),
                    ("KEEP", "K1", "2009-01-01", "2009-12-31", "5853"),
                    ("DROP", "D1", "2009-01-01", "2010-01-01", "5853"),
                    ("END", "X1", "2010-10-01", "2010-10-01", "5853"),
                ]
            ),
        ],
        ignore_index=True,
    )


def _no_target_only() -> pd.DataFrame:
    return _custom([("NONE", "NONE-1", "2008-02-01", "2008-02-01", "4019")])


def _scenarios() -> tuple[pd.DataFrame, ...]:
    return (
        _claims(),
        _claims().loc[lambda frame: frame["claim_id"] != "J003"],
        _claims().iloc[0:0].copy(),
        _adversarial_ties(),
        _spanning_early_claim(),
        _spanning_only_claim(),
        _spanning_claim_hides_later_claim(),
        _late_target_no_target_and_window_edges(),
        _no_target_only(),
    )


def _normalize(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    result = frame[columns].copy()
    for column in result.columns:
        if column.endswith("_date") or column in {"observation_end", "follow_up_end"}:
            result[column] = pd.to_datetime(result[column], errors="coerce").dt.strftime(
                "%Y-%m-%d"
            )
    return result.reset_index(drop=True)


def _load_duckdb(connection: Any, claims: pd.DataFrame) -> None:
    connection.execute("DROP SCHEMA IF EXISTS raw_synpuf CASCADE")
    connection.execute("CREATE SCHEMA raw_synpuf")
    connection.register("claims_input", claims)
    connection.execute("CREATE TABLE raw_synpuf.claims AS SELECT * FROM claims_input")
    connection.unregister("claims_input")


def _assert_reconciled(python: Any, first: dict[str, pd.DataFrame]) -> None:
    assert list(first["events"].columns) == EVENT_COLUMNS
    assert list(first["summaries"].columns) == SUMMARY_COLUMNS
    assert list(first["survival"].columns) == SURVIVAL_COLUMNS
    assert set(first["events"]["evidence_type"]) <= {"public_synthetic"}
    assert set(first["summaries"]["evidence_type"]) <= {"public_synthetic"}
    assert set(first["survival"]["evidence_type"]) <= {"public_synthetic"}
    assert set(first["metadata"]["evidence_type"]) == {"public_synthetic"}
    pd.testing.assert_frame_equal(
        _normalize(python.events, EVENT_COLUMNS),
        _normalize(first["events"], EVENT_COLUMNS),
        check_dtype=False,
    )
    pd.testing.assert_frame_equal(
        _normalize(python.summaries, SUMMARY_COLUMNS),
        _normalize(first["summaries"], SUMMARY_COLUMNS),
        check_dtype=False,
    )
    pd.testing.assert_frame_equal(
        _normalize(python.survival, SURVIVAL_COLUMNS),
        _normalize(first["survival"], SURVIVAL_COLUMNS),
        check_dtype=False,
    )
    metadata_value: Any = first["metadata"].loc[0, "median_survival"]
    if pd.isna(metadata_value):
        assert python.median_survival is None
    else:
        assert float(metadata_value) == python.median_survival


def _run_and_compare(connection: Any, claims: pd.DataFrame) -> None:
    python = build_journey_output(claims)
    _load_duckdb(connection, claims)
    connection.execute(SQL)
    first = {
        "events": connection.execute(
            "SELECT * FROM analytics_synthetic.mart_journeys "
            "ORDER BY synthetic_id, event_date, claim_id"
        ).fetchdf(),
        "summaries": connection.execute(
            "SELECT * FROM analytics_synthetic.mart_journey_summaries ORDER BY synthetic_id"
        ).fetchdf(),
        "survival": connection.execute(
            "SELECT * FROM analytics_synthetic.mart_journey_survival ORDER BY time"
        ).fetchdf(),
        "metadata": connection.execute(
            "SELECT * FROM analytics_synthetic.mart_journey_survival_metadata"
        ).fetchdf(),
    }
    # A same-session rerun must be safe and must preserve exact values.
    connection.execute(SQL)
    second = {
        "events": connection.execute(
            "SELECT * FROM analytics_synthetic.mart_journeys "
            "ORDER BY synthetic_id, event_date, claim_id"
        ).fetchdf(),
        "summaries": connection.execute(
            "SELECT * FROM analytics_synthetic.mart_journey_summaries ORDER BY synthetic_id"
        ).fetchdf(),
        "survival": connection.execute(
            "SELECT * FROM analytics_synthetic.mart_journey_survival ORDER BY time"
        ).fetchdf(),
        "metadata": connection.execute(
            "SELECT * FROM analytics_synthetic.mart_journey_survival_metadata"
        ).fetchdf(),
    }
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name], check_dtype=False)

    _assert_reconciled(python, first)


def test_duckdb_sql_reconciles_standard_all_censored_empty_and_ties() -> None:
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect()
    try:
        for claims in _scenarios():
            _run_and_compare(connection, claims)
            fresh = duckdb.connect()
            try:
                _run_and_compare(fresh, claims)
            finally:
                fresh.close()
    finally:
        connection.close()


def test_duckdb_and_python_agree_on_spanning_claim_regression() -> None:
    duckdb = pytest.importorskip("duckdb")
    claims = _spanning_claim_hides_later_claim()
    python = build_journey_output(claims)
    connection = duckdb.connect()
    try:
        _run_and_compare(connection, claims)
        sql_summary = connection.execute(
            "SELECT * FROM analytics_synthetic.mart_journey_summaries"
        ).fetchdf()
        sql_events = connection.execute(
            "SELECT claim_id FROM analytics_synthetic.mart_journeys ORDER BY event_date"
        ).fetchdf()
    finally:
        connection.close()
    assert list(sql_events["claim_id"]) == ["C2", "C3"]
    assert list(python.events["claim_id"]) == ["C2", "C3"]
    for summary in (python.summaries.iloc[0], sql_summary.iloc[0]):
        assert pd.Timestamp(summary["persistence_date"]) == pd.Timestamp("2009-02-15")
        assert bool(summary["event_observed"])
        assert int(summary["duration_days"]) == 351


def test_duckdb_excludes_people_without_a_target_from_survival() -> None:
    duckdb = pytest.importorskip("duckdb")
    claims = _late_target_no_target_and_window_edges()
    connection = duckdb.connect()
    try:
        _run_and_compare(connection, claims)
        summary_ids = connection.execute(
            "SELECT synthetic_id FROM analytics_synthetic.mart_journey_summaries"
        ).fetchdf()["synthetic_id"]
        max_at_risk = connection.execute(
            "SELECT MAX(at_risk) FROM analytics_synthetic.mart_journey_survival"
        ).fetchone()
        bad_durations = connection.execute(
            "SELECT COUNT(*) FROM analytics_synthetic.mart_journey_summaries "
            "WHERE duration_days < 0 OR duration_days > 364 OR target_date < index_date"
        ).fetchone()
    finally:
        connection.close()
    assert "NONE" not in set(summary_ids)
    assert max_at_risk is not None and max_at_risk[0] == len(summary_ids)
    assert bad_durations == (0,)


def test_postgres_sql_reconciles_when_explicit_test_database_is_available() -> None:
    psycopg = pytest.importorskip("psycopg")
    database_url = os.environ.get("CKD_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("CKD_TEST_POSTGRES_URL is not configured")
    try:
        connection = psycopg.connect(database_url, autocommit=True)
    except Exception as error:  # pragma: no cover - depends on local service
        pytest.skip(f"configured PostgreSQL is unavailable: {error}")
    try:
        for claims in _scenarios():
            _run_postgres_scenario(connection, claims)
    finally:
        connection.close()
    fresh = psycopg.connect(database_url, autocommit=True)
    try:
        _run_postgres_scenario(fresh, _claims())
    finally:
        fresh.close()


def _run_postgres_scenario(connection: Any, claims: pd.DataFrame) -> None:
    python = build_journey_output(claims)
    with connection.cursor() as cursor:
        cursor.execute("DROP SCHEMA IF EXISTS raw_synpuf CASCADE")
        cursor.execute("CREATE SCHEMA raw_synpuf")
        cursor.execute(
            """CREATE TABLE raw_synpuf.claims (
                source_release text, beneficiary_id text, claim_id text,
                claim_type text, service_from_date date, service_through_date date,
                diagnosis_code text, provider_id text, payment_amount_usd double precision,
                year integer, evidence_type text
            )"""
        )
        cursor.executemany(
            "INSERT INTO raw_synpuf.claims VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [tuple(row) for row in claims.itertuples(index=False, name=None)],
        )

        def fetch(query: str) -> pd.DataFrame:
            cursor.execute(query)
            rows = cursor.fetchall()
            columns = [column.name for column in cursor.description]
            return pd.DataFrame(rows, columns=columns)

        def outputs() -> dict[str, pd.DataFrame]:
            return {
                "events": fetch(
                    "SELECT * FROM analytics_synthetic.mart_journeys "
                    "ORDER BY synthetic_id, event_date, claim_id"
                ),
                "summaries": fetch(
                    "SELECT * FROM analytics_synthetic.mart_journey_summaries ORDER BY synthetic_id"
                ),
                "survival": fetch(
                    "SELECT * FROM analytics_synthetic.mart_journey_survival ORDER BY time"
                ),
                "metadata": fetch(
                    "SELECT * FROM analytics_synthetic.mart_journey_survival_metadata"
                ),
            }

        cursor.execute(SQL)
        first = outputs()
        cursor.execute(SQL)
        second = outputs()
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name], check_dtype=False)
    _assert_reconciled(python, first)
