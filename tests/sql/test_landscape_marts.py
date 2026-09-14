from __future__ import annotations

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
def landscape_db(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    db = duckdb.connect()
    db.execute("CREATE SCHEMA raw_meps")
    db.execute("CREATE SCHEMA raw_partd")
    db.execute("CREATE SCHEMA raw_trials")
    db.execute("CREATE SCHEMA analytics_observed")

    meps = ingest_meps(FIXTURE_DIR / "meps.csv", cache_dir=tmp_path / "meps")
    db.execute(
        """
        CREATE TABLE raw_meps.events (
          source_release VARCHAR, event_id VARCHAR, person_id VARCHAR, year INTEGER,
          condition_code VARCHAR, event_type VARCHAR, rx_name VARCHAR,
          expenditure_usd DOUBLE, person_weight DOUBLE, variance_stratum INTEGER,
          variance_psu INTEGER, evidence_type VARCHAR
        )
        """
    )
    db.executemany(
        "INSERT INTO raw_meps.events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [tuple(row.get(column) for column in (
            "source_release", "event_id", "person_id", "year", "condition_code",
            "event_type", "rx_name", "expenditure_usd", "person_weight",
            "variance_stratum", "variance_psu", "evidence_type"
        )) for row in meps.valid],
    )

    partd = ingest_partd(FIXTURE_DIR / "partd.csv", cache_dir=tmp_path / "partd")
    db.execute(
        """
        CREATE TABLE raw_partd.records (
          source_release VARCHAR, provider_npi VARCHAR, provider_state VARCHAR,
          drug_name VARCHAR, generic_name VARCHAR, total_claim_count BIGINT,
          total_30_day_fill_count DOUBLE, total_drug_cost_usd DOUBLE, year INTEGER,
          evidence_type VARCHAR
        )
        """
    )
    db.executemany(
        "INSERT INTO raw_partd.records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [tuple(row.get(column) for column in (
            "source_release", "provider_npi", "provider_state", "drug_name",
            "generic_name", "total_claim_count", "total_30_day_fill_count",
            "total_drug_cost_usd", "year", "evidence_type"
        )) for row in partd.valid],
    )

    trials = ingest_trials(FIXTURE_DIR / "clinicaltrials.json", cache_dir=tmp_path / "trials")
    db.execute(
        """
        CREATE TABLE raw_trials.studies (
          nct_id VARCHAR, brief_title VARCHAR, overall_status VARCHAR, phase VARCHAR,
          enrollment BIGINT, condition VARCHAR, intervention VARCHAR, sponsor VARCHAR,
          country VARCHAR, last_update_date DATE, study_type VARCHAR, evidence_type VARCHAR
        )
        """
    )
    db.executemany(
        "INSERT INTO raw_trials.studies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [tuple(row.get(column) for column in (
            "nct_id", "brief_title", "overall_status", "phase", "enrollment",
            "condition", "intervention", "sponsor", "country", "last_update_date",
            "study_type", "evidence_type"
        )) for row in trials.valid],
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
    columns = landscape_db.sql(
        "describe analytics_observed.mart_partd_prescribing"
    ).df()["column_name"].tolist()
    assert not any("beneficiary_id" in name.lower() for name in columns)
    assert not any("person_id" in name.lower() for name in columns)


def test_trial_status_totals_reconcile(landscape_db: duckdb.DuckDBPyConnection) -> None:
    raw = landscape_db.sql("select count(*) from raw_trials.studies").fetchone()[0]
    mart = landscape_db.sql(
        "select sum(study_count) from analytics_observed.mart_trial_status"
    ).fetchone()[0]
    assert raw == mart


def test_meps_mart_preserves_weighted_utilization_and_source_scope(
    landscape_db: duckdb.DuckDBPyConnection,
) -> None:
    rows = landscape_db.sql(
        """
        SELECT year, condition_code, event_type, weighted_event_count,
               weighted_expenditure_usd, source_population, source_grain
        FROM analytics_observed.mart_meps_utilization
        WHERE event_type = 'prescription'
        """
    ).fetchall()
    assert rows[0][0:3] == (2021, "I10", "prescription")
    assert rows[0][3] == pytest.approx(4788.1)
    assert rows[0][4] == pytest.approx(32.10 * 4788.1)
    assert "MEPS" in rows[0][5]
    assert "event" in rows[0][6].lower()


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
    total = landscape_db.sql(
        "SELECT sum(total_drug_cost_usd) FROM analytics_observed.mart_partd_prescribing"
    ).fetchone()[0]
    assert total == pytest.approx(84628.90)


def test_trial_analysis_returns_reconciled_status_and_composition(tmp_path: Path) -> None:
    result = summarize_trial_status(
        ingest_trials(FIXTURE_DIR / "clinicaltrials.json", cache_dir=tmp_path / "trials").valid
    )
    assert result[0]["overall_status"] == "RECRUITING"
    assert result[0]["study_count"] == 1
    assert result[0]["total_reported_enrollment"] == 120
