"""Optional PostgreSQL integration contract for the committed marts.

Run with ``CKD_POSTGRES_URL`` and the ``postgres`` extra to exercise the same
source-specific views on PostgreSQL.  The DuckDB suite remains the fast CI gate.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(
    not os.environ.get("CKD_POSTGRES_URL"),
    reason="set CKD_POSTGRES_URL to run the PostgreSQL integration contract",
)
def test_landscape_marts_execute_on_postgresql() -> None:
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError:
        pytest.fail("CKD_POSTGRES_URL is configured but psycopg is not installed")
    with (
        psycopg.connect(os.environ["CKD_POSTGRES_URL"]) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("CREATE SCHEMA IF NOT EXISTS raw_meps")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS raw_partd")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS raw_trials")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS analytics_observed")
        cursor.execute("DROP TABLE IF EXISTS raw_meps.people")
        cursor.execute("DROP TABLE IF EXISTS raw_partd.records")
        cursor.execute("DROP TABLE IF EXISTS raw_trials.studies")
        cursor.execute("""
                CREATE TABLE raw_meps.people (
                    source_release TEXT, person_id TEXT, year INTEGER,
                    dcs_eligible INTEGER, diabetes_reported INTEGER,
                    kidney_problem_proxy INTEGER, total_expenditure_usd DOUBLE PRECISION,
                    office_visits INTEGER, outpatient_visits INTEGER,
                    emergency_visits INTEGER, inpatient_stays INTEGER,
                    prescription_medicines INTEGER, person_weight DOUBLE PRECISION,
                    proxy_weight DOUBLE PRECISION, variance_stratum INTEGER,
                    variance_psu INTEGER, evidence_type TEXT,
                    source_retrieved_at TEXT, source_manifest_checksum TEXT
                )
            """)
        cursor.execute("""
                INSERT INTO raw_meps.people VALUES
                ('HC-243-2022', 'fixture', 2022, 1, 1, 1, 10, 1, 0, 0, 0, 1,
                 10, 10, 1, 1, 'fixture_only', '2026-09-11T00:00:00Z', 'fixture')
            """)
        cursor.execute("""
                CREATE TABLE raw_partd.records (
                    source_release TEXT, provider_npi TEXT, provider_state TEXT,
                    drug_name TEXT, generic_name TEXT, total_claim_count BIGINT,
                    total_30_day_fill_count DOUBLE PRECISION, total_drug_cost_usd DOUBLE PRECISION,
                    year INTEGER, evidence_type TEXT, source_retrieved_at TEXT,
                    source_manifest_checksum TEXT
                )
            """)
        cursor.execute("""
                INSERT INTO raw_partd.records VALUES
                ('2024', 'fixture-provider', 'PA', 'Jardiance', 'Empagliflozin', 11, 11, 100, 2024,
                 'fixture_only', '2026-09-11T00:00:00Z', 'fixture')
            """)
        cursor.execute("""
                CREATE TABLE raw_trials.studies (
                    nct_id TEXT, brief_title TEXT, overall_status TEXT, phase TEXT,
                    enrollment BIGINT, condition TEXT, intervention TEXT, sponsor TEXT,
                    country TEXT, last_update_date DATE, study_type TEXT, evidence_type TEXT,
                    source_retrieved_at TEXT, source_manifest_checksum TEXT
                )
            """)
        cursor.execute("""
                INSERT INTO raw_trials.studies VALUES
                ('fixture-trial', 'fixture', 'RECRUITING', 'PHASE2', NULL, 'CKD', 'drug',
                 'Fixture sponsor', 'United States', DATE '2026-01-01', 'INTERVENTIONAL',
                 'fixture_only', '2026-09-11T00:00:00Z', 'fixture')
            """)
        for script in (
            "sql/marts/mart_meps_utilization.sql",
            "sql/marts/mart_partd_prescribing.sql",
            "sql/marts/mart_trial_landscape.sql",
        ):
            cursor.execute((ROOT / script).read_text(encoding="utf-8"))
        cursor.execute("SELECT COUNT(*) FROM analytics_observed.mart_meps_utilization")
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT COUNT(*), COUNT(DISTINCT (source_release, year, kidney_proxy_status, "
            "evidence_type, source_retrieved_at, source_manifest_checksum)), "
            "COUNT(DISTINCT evidence_type) "
            "FROM analytics_observed.mart_meps_utilization"
        )
        assert cursor.fetchone() == (1, 1, 1)
        cursor.execute("SELECT COUNT(*) FROM analytics_observed.mart_partd_prescribing")
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT COUNT(*), COUNT(DISTINCT (source_release, year, provider_npi, "
            "provider_state, generic_name, drug_name, evidence_type, source_retrieved_at, "
            "source_manifest_checksum)), COUNT(DISTINCT evidence_type), "
            "SUM(total_claim_count) "
            "FROM analytics_observed.mart_partd_prescribing"
        )
        assert cursor.fetchone() == (1, 1, 1, 11)
        cursor.execute("SELECT COUNT(*) FROM analytics_observed.mart_trial_status")
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT SUM(study_count), COUNT(DISTINCT overall_status), "
            "COUNT(DISTINCT evidence_type), COUNT(DISTINCT source_retrieved_at), "
            "COUNT(DISTINCT source_manifest_checksum) "
            "FROM analytics_observed.mart_trial_status"
        )
        assert cursor.fetchone() == (1, 1, 1, 1, 1)
        cursor.execute(
            "SELECT total_reported_enrollment, studies_with_reported_enrollment, "
            "evidence_type, source_retrieved_at, source_manifest_checksum "
            "FROM analytics_observed.mart_trial_status"
        )
        trial_row = cursor.fetchone()
        assert trial_row == (None, 0, "fixture_only", "2026-09-11T00:00:00Z", "fixture")
        cursor.execute(
            "SELECT COUNT(*) FROM analytics_observed.mart_partd_prescribing "
            "WHERE source_release = '2024' AND provider_npi = 'fixture-provider'"
        )
        assert cursor.fetchone()[0] == 1
