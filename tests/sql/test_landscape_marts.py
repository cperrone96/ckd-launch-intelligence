from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import duckdb
import pytest

from ckd_intelligence.analysis.trials import summarize_trial_status
from ckd_intelligence.ingestion.meps import ingest_meps
from ckd_intelligence.ingestion.partd import ingest_partd
from ckd_intelligence.ingestion.trials import ingest_trials

ROOT = Path(__file__).parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "ingestion"


@pytest.fixture()
def landscape_db(tmp_path: Path) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    db = duckdb.connect()
    db.execute("CREATE SCHEMA raw_meps")
    db.execute("CREATE SCHEMA raw_partd")
    db.execute("CREATE SCHEMA raw_trials")
    db.execute("CREATE SCHEMA analytics_observed")

    meps = ingest_meps(FIXTURE_DIR / "meps.csv", cache_dir=tmp_path / "meps")
    db.execute(
        """
        CREATE TABLE raw_meps.people (
          source_release VARCHAR, person_id VARCHAR, year INTEGER, dcs_eligible INTEGER,
          diabetes_reported INTEGER, kidney_problem_proxy INTEGER,
          total_expenditure_usd DOUBLE, office_visits INTEGER, outpatient_visits INTEGER,
          emergency_visits INTEGER, inpatient_stays INTEGER, prescription_medicines INTEGER,
          person_weight DOUBLE, proxy_weight DOUBLE, variance_stratum INTEGER,
          variance_psu INTEGER, evidence_type VARCHAR, source_retrieved_at VARCHAR,
          source_manifest_checksum VARCHAR
        )
        """
    )
    db.executemany(
        (
            "INSERT INTO raw_meps.people VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        ),
        [
            tuple(
                row.get(column)
                for column in (
                    "source_release",
                    "person_id",
                    "year",
                    "dcs_eligible",
                    "diabetes_reported",
                    "kidney_problem_proxy",
                    "total_expenditure_usd",
                    "office_visits",
                    "outpatient_visits",
                    "emergency_visits",
                    "inpatient_stays",
                    "prescription_medicines",
                    "person_weight",
                    "proxy_weight",
                    "variance_stratum",
                    "variance_psu",
                    "evidence_type",
                )
            )
            + (None, None)
            for row in meps.valid
        ],
    )
    db.execute(
        "UPDATE raw_meps.people SET source_retrieved_at='2026-09-11T21:20:41Z', "
        "source_manifest_checksum='fixture-meps'"
    )

    partd = ingest_partd(FIXTURE_DIR / "partd.csv", cache_dir=tmp_path / "partd")
    db.execute(
        """
        CREATE TABLE raw_partd.records (
          source_release VARCHAR, provider_npi VARCHAR, provider_state VARCHAR,
          drug_name VARCHAR, generic_name VARCHAR, total_claim_count BIGINT,
          total_30_day_fill_count DOUBLE, total_drug_cost_usd DOUBLE, year INTEGER,
          evidence_type VARCHAR, source_retrieved_at VARCHAR, source_manifest_checksum VARCHAR
        )
        """
    )
    db.executemany(
        "INSERT INTO raw_partd.records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            tuple(
                row.get(column)
                for column in (
                    "source_release",
                    "provider_npi",
                    "provider_state",
                    "drug_name",
                    "generic_name",
                    "total_claim_count",
                    "total_30_day_fill_count",
                    "total_drug_cost_usd",
                    "year",
                    "evidence_type",
                )
            )
            + (None, None)
            for row in partd.valid
        ],
    )
    db.execute(
        "UPDATE raw_partd.records SET source_retrieved_at='2026-09-11T21:20:41Z', "
        "source_manifest_checksum='fixture-partd'"
    )

    trials = ingest_trials(FIXTURE_DIR / "clinicaltrials.json", cache_dir=tmp_path / "trials")
    db.execute(
        """
        CREATE TABLE raw_trials.studies (
          nct_id VARCHAR, brief_title VARCHAR, overall_status VARCHAR, phase VARCHAR,
          enrollment BIGINT, condition VARCHAR, intervention VARCHAR, sponsor VARCHAR,
          country VARCHAR, last_update_date DATE, study_type VARCHAR, evidence_type VARCHAR,
          source_retrieved_at VARCHAR, source_manifest_checksum VARCHAR
        )
        """
    )
    db.executemany(
        "INSERT INTO raw_trials.studies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            tuple(
                row.get(column)
                for column in (
                    "nct_id",
                    "brief_title",
                    "overall_status",
                    "phase",
                    "enrollment",
                    "condition",
                    "intervention",
                    "sponsor",
                    "country",
                    "last_update_date",
                    "study_type",
                    "evidence_type",
                )
            )
            + (None, None)
            for row in trials.valid
        ],
    )
    db.execute(
        "UPDATE raw_trials.studies SET source_retrieved_at='2026-09-09T14:30:00Z', "
        "source_manifest_checksum='fixture-trials'"
    )
    db.execute("SET TimeZone='UTC'")
    for script in (
        "sql/marts/mart_meps_utilization.sql",
        "sql/marts/mart_partd_prescribing.sql",
        "sql/marts/mart_trial_landscape.sql",
    ):
        db.execute((ROOT / script).read_text(encoding="utf-8"))
    yield db
    db.close()


def test_partd_mart_has_no_beneficiary_identifier(landscape_db: duckdb.DuckDBPyConnection) -> None:
    columns = (
        landscape_db.sql("describe analytics_observed.mart_partd_prescribing")
        .df()["column_name"]
        .tolist()
    )
    assert not any("beneficiary_id" in name.lower() for name in columns)
    assert not any("person_id" in name.lower() for name in columns)


def test_trial_status_totals_reconcile(landscape_db: duckdb.DuckDBPyConnection) -> None:
    raw_result = landscape_db.sql("select count(*) from raw_trials.studies").fetchone()
    mart_result = landscape_db.sql(
        "select sum(study_count) from analytics_observed.mart_trial_status"
    ).fetchone()
    assert raw_result is not None and mart_result is not None
    raw = raw_result[0]
    mart = mart_result[0]
    assert raw == mart


def test_meps_mart_preserves_weighted_utilization_and_source_scope(
    landscape_db: duckdb.DuckDBPyConnection,
) -> None:
    rows = landscape_db.sql(
        """
        SELECT year, kidney_proxy_status, weighted_population,
               weighted_expenditure_usd, source_population, source_grain
        FROM analytics_observed.mart_meps_utilization
        WHERE kidney_proxy_status = 'proxy_positive'
        """
    ).fetchall()
    assert rows
    row = rows[0]
    assert row[0:3] == (2022, "proxy_positive", pytest.approx(5000.0))
    assert row[3] == pytest.approx(145.25 * 5000.0)
    assert "MEPS" in row[4]
    assert "person-year" in row[5].lower()


def test_partd_grain_is_provider_drug_year_and_cost_is_reconciled(
    landscape_db: duckdb.DuckDBPyConnection,
) -> None:
    duplicate_grains = landscape_db.sql(
        """
        SELECT provider_npi, provider_state, generic_name, year, count(*)
        FROM analytics_observed.mart_partd_prescribing
        GROUP BY 1, 2, 3, 4
        HAVING count(*) > 1
        """
    ).fetchall()
    assert duplicate_grains == []
    total_result = landscape_db.sql(
        "SELECT sum(total_drug_cost_usd) FROM analytics_observed.mart_partd_prescribing"
    ).fetchone()
    assert total_result is not None
    total = total_result[0]
    assert total == pytest.approx(84628.90)


def test_trial_analysis_returns_reconciled_status_and_composition(tmp_path: Path) -> None:
    result = summarize_trial_status(
        ingest_trials(FIXTURE_DIR / "clinicaltrials.json", cache_dir=tmp_path / "trials").valid
    )
    assert result
    assert result[0]["overall_status"] == "RECRUITING"
    assert result[0]["study_count"] == 1
    assert result[0]["total_reported_enrollment"] == 120
