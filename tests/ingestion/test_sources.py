from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ckd_intelligence.ingestion.meps import ingest_meps
from ckd_intelligence.ingestion.nhanes import ingest_nhanes
from ckd_intelligence.ingestion.partd import ingest_partd
from ckd_intelligence.ingestion.synpuf import ingest_synpuf
from ckd_intelligence.ingestion.trials import ingest_trials
from ckd_intelligence.quality.contracts import IngestionResult

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ingestion"


@pytest.fixture(params=["nhanes", "meps", "partd", "clinicaltrials", "synpuf"])
def source_case(request: pytest.FixtureRequest) -> tuple[str, Path]:
    extension = "json" if request.param == "clinicaltrials" else "csv"
    return request.param, FIXTURES / f"{request.param}.{extension}"


def _ingest(source: str, path: Path, cache_dir: Path) -> IngestionResult:
    ingestors = {
        "nhanes": ingest_nhanes,
        "meps": ingest_meps,
        "partd": ingest_partd,
        "clinicaltrials": ingest_trials,
        "synpuf": ingest_synpuf,
    }
    return ingestors[source](path, cache_dir=cache_dir)


def test_each_source_preserves_contract_and_provenance(
    source_case: tuple[str, Path], tmp_path: Path
) -> None:
    source, fixture = source_case

    result = _ingest(source, fixture, tmp_path / "cache")

    assert result.manifest.source == source
    assert result.manifest.input_checksum == hashlib.sha256(fixture.read_bytes()).hexdigest()
    assert result.manifest.byte_count == fixture.stat().st_size
    assert result.manifest.record_count == len(result.valid) + len(result.quarantine)
    assert result.manifest.valid_count == len(result.valid)
    assert result.manifest.quarantine_count == len(result.quarantine)
    assert result.manifest.population
    assert result.manifest.grain
    assert result.manifest.coverage_start is not None
    assert result.manifest.coverage_end is not None
    assert result.manifest.cache_path is not None
    assert Path(result.manifest.cache_path).read_bytes() == fixture.read_bytes()
    assert set(result.valid["evidence_type"]) == {result.manifest.evidence_type}


def test_repeated_ingestion_is_byte_and_manifest_deterministic(
    source_case: tuple[str, Path], tmp_path: Path
) -> None:
    source, fixture = source_case
    cache_dir = tmp_path / "cache"

    first = _ingest(source, fixture, cache_dir)
    second = _ingest(source, fixture, cache_dir)

    assert first == second
    assert first.manifest.cache_path == second.manifest.cache_path
    assert len(list(cache_dir.rglob("*.*"))) == 1


def test_manifests_and_batches_are_immutable(tmp_path: Path) -> None:
    result = ingest_nhanes(FIXTURES / "nhanes.csv", cache_dir=tmp_path)

    with pytest.raises(FrozenInstanceError):
        result.manifest.source = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.valid.records[0]["respondent_id"] = "changed"  # type: ignore[index]


def test_synpuf_is_never_labeled_observed(tmp_path: Path) -> None:
    result = ingest_synpuf(FIXTURES / "synpuf.csv", cache_dir=tmp_path)

    assert set(result.valid["evidence_type"]) == {"public_synthetic"}
    assert result.manifest.evidence_type == "public_synthetic"


def test_trial_ingestion_preserves_api_update_date(tmp_path: Path) -> None:
    result = ingest_trials(FIXTURES / "clinicaltrials.json", cache_dir=tmp_path)

    assert result.manifest.source_updated_at == "2026-09-09T14:30:00Z"
    assert result.valid[0]["last_update_date"] == "2026-09-08"


@pytest.mark.parametrize(
    ("source", "invalid_fixture", "expected_reasons"),
    [
        (
            "nhanes",
            "nhanes_invalid.csv",
            {
                "age_years:missing_sentinel",
                "respondent_id:duplicate_key",
                "sample_weight:out_of_range",
            },
        ),
        (
            "meps",
            "meps_invalid.csv",
            {"expenditure_usd:invalid_number", "event_id:duplicate_key", "event_type:invalid_code"},
        ),
        (
            "partd",
            "partd_invalid.csv",
            {
                "provider_npi:invalid_code",
                "record_key:duplicate_key",
                "total_claim_count:out_of_range",
            },
        ),
        (
            "clinicaltrials",
            "clinicaltrials_invalid.json",
            {
                "last_update_date:invalid_date",
                "nct_id:duplicate_key",
                "overall_status:invalid_code",
            },
        ),
        (
            "synpuf",
            "synpuf_invalid.csv",
            {
                "claim_id:duplicate_key",
                "claim_type:invalid_code",
                "service_date_range:invalid_range",
            },
        ),
    ],
)
def test_invalid_rows_are_quarantined_with_explicit_reasons(
    source: str,
    invalid_fixture: str,
    expected_reasons: set[str],
    tmp_path: Path,
) -> None:
    result = _ingest(source, FIXTURES / invalid_fixture, tmp_path / source)
    reasons = {reason for item in result.quarantine for reason in item.reasons}

    assert not result.valid
    assert expected_reasons <= reasons
    assert all(item.reasons for item in result.quarantine)
    assert result.manifest.quarantine_count == result.manifest.record_count


def test_missing_required_columns_fail_closed(tmp_path: Path) -> None:
    malformed = tmp_path / "missing-columns.csv"
    cache_dir = tmp_path / "cache"
    malformed.write_text("respondent_id,age_years\n1,65\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing required columns"):
        ingest_nhanes(malformed, cache_dir=cache_dir)
    cached_files = [path for path in cache_dir.rglob("*") if path.is_file()]
    assert len(cached_files) == 1
    assert cached_files[0].read_bytes() == malformed.read_bytes()


def test_numeric_sentinel_codes_are_field_specific(tmp_path: Path) -> None:
    valid_cost = tmp_path / "partd-cost.csv"
    valid_cost.write_text(
        "provider_npi,provider_state,drug_name,generic_name,total_claim_count,"
        "total_30_day_fill_count,total_drug_cost_usd,year\n"
        "1234567890,PA,Example,example,12,12.5,9999,2024\n",
        encoding="utf-8",
    )

    result = ingest_partd(valid_cost, cache_dir=tmp_path / "cache")

    assert result.valid[0]["total_drug_cost_usd"] == 9999.0


def test_non_finite_numeric_values_are_quarantined(tmp_path: Path) -> None:
    invalid = tmp_path / "meps-nan.csv"
    invalid.write_text(
        "event_id,person_id,year,condition_code,event_type,rx_name,expenditure_usd,"
        "person_weight,variance_stratum,variance_psu\n"
        "E1,P1,2021,N18,office_visit,,nan,5021.4,12,1\n",
        encoding="utf-8",
    )

    result = ingest_meps(invalid, cache_dir=tmp_path / "cache")

    assert result.quarantine[0].reasons == ("expenditure_usd:invalid_number",)


def test_wrong_top_level_trials_shape_fails_closed(tmp_path: Path) -> None:
    malformed = tmp_path / "trials.json"
    malformed.write_text(json.dumps([{"nct_id": "NCT00000001"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        ingest_trials(malformed, cache_dir=tmp_path / "cache")


def test_only_https_urls_are_accepted(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        ingest_nhanes("http://example.test/nhanes.csv", cache_dir=tmp_path)


def test_cross_source_person_linkage_field_is_rejected(tmp_path: Path) -> None:
    unsafe = tmp_path / "partd.csv"
    unsafe.write_text(
        "provider_npi,provider_state,drug_name,generic_name,total_claim_count,"
        "total_30_day_fill_count,total_drug_cost_usd,year,beneficiary_id\n"
        "1234567890,PA,Example,example,12,12.5,120.00,2024,BENE1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Forbidden patient-level fields"):
        ingest_partd(unsafe, cache_dir=tmp_path / "cache")
