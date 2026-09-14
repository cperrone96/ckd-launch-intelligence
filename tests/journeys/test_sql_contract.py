from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from ckd_intelligence.journeys.synpuf import build_journey_output

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
    return pd.read_csv(FIXTURE)


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
        scenarios = (
            _claims(),
            _claims().loc[lambda frame: frame["claim_id"] != "J003"],
            _claims().iloc[0:0].copy(),
            _adversarial_ties(),
            _spanning_early_claim(),
        )
        for claims in scenarios:
            _run_and_compare(connection, claims)
            fresh = duckdb.connect()
            try:
                _run_and_compare(fresh, claims)
            finally:
                fresh.close()
    finally:
        connection.close()


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
        for claims in (
            _claims(),
            _claims().loc[lambda frame: frame["claim_id"] != "J003"],
            _claims().iloc[0:0].copy(),
            _adversarial_ties(),
            _spanning_early_claim(),
        ):
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
