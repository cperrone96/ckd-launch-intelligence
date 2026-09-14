import pytest
from pydantic import ValidationError

from ckd_intelligence.config import DatabaseBackend, Settings


def test_local_runtime_defaults_to_duckdb() -> None:
    settings = Settings()

    assert settings.database_backend is DatabaseBackend.DUCKDB
    assert settings.database_url == "duckdb:///data/ckd_intelligence.duckdb"


def test_schema_contract_separates_sources_and_evidence_types() -> None:
    settings = Settings()

    assert settings.raw_schemas == (
        "raw_nhanes",
        "raw_meps",
        "raw_partd",
        "raw_trials",
        "raw_synpuf",
    )
    assert settings.observed_schema == "analytics_observed"
    assert settings.synthetic_schema == "analytics_synthetic"
    assert settings.observed_schema != settings.synthetic_schema
    assert len(settings.all_schemas) == len(set(settings.all_schemas)) == 7


def test_schema_contract_rejects_overlapping_namespaces() -> None:
    with pytest.raises(ValidationError, match="Schema names must be unique"):
        Settings(observed_schema="analytics_results", synthetic_schema="analytics_results")


def test_schema_contract_rejects_non_identifier_names() -> None:
    with pytest.raises(ValidationError, match="valid SQL identifiers"):
        Settings(observed_schema="analytics_observed; DROP SCHEMA raw_nhanes")
