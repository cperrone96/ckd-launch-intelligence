from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import FrozenInstanceError
from io import BytesIO
from pathlib import Path

import pytest

from ckd_intelligence.ingestion._common import native_scalar_text
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
            {"total_expenditure_usd:invalid_number", "person_id:duplicate_key"},
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
        "source_release,provider_npi,provider_state,drug_name,generic_name,total_claim_count,"
        "total_30_day_fill_count,total_drug_cost_usd,year\n"
        "2024,1234567890,PA,Example,example,12,12.5,9999,2024\n",
        encoding="utf-8",
    )

    result = ingest_partd(valid_cost, cache_dir=tmp_path / "cache")

    assert result.valid[0]["total_drug_cost_usd"] == 9999.0


def test_non_finite_numeric_values_are_quarantined(tmp_path: Path) -> None:
    invalid = tmp_path / "meps-nan.csv"
    invalid.write_text(
        "source_release,person_id,year,dcs_eligible,diabetes_reported,kidney_problem_proxy,"
        "total_expenditure_usd,office_visits,outpatient_visits,emergency_visits,inpatient_stays,"
        "prescription_medicines,person_weight,proxy_weight,variance_stratum,variance_psu\n"
        "HC-243-2022,P1,2022,1,1,1,nan,2,0,1,0,3,5021.4,5000.0,12,1\n",
        encoding="utf-8",
    )

    result = ingest_meps(invalid, cache_dir=tmp_path / "cache")

    assert result.quarantine[0].reasons == ("total_expenditure_usd:invalid_number",)


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
        "source_release,provider_npi,provider_state,drug_name,generic_name,total_claim_count,"
        "total_30_day_fill_count,total_drug_cost_usd,year,beneficiary_id\n"
        "2024,1234567890,PA,Example,example,12,12.5,120.00,2024,BENE1\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Forbidden patient-level fields"):
        ingest_partd(unsafe, cache_dir=tmp_path / "cache")


@pytest.mark.parametrize(
    ("source", "fixture", "old", "spoof"),
    [
        ("nhanes", "nhanes.csv", "2017-2018", "2015-2016"),
        ("meps", "meps.csv", "HC-243-2022", "HC-999-2020"),
        ("partd", "partd.csv", "2024", "2023"),
        ("synpuf", "synpuf.csv", "2008-2010", "2011-2013"),
    ],
)
def test_spoofed_release_identity_fails_before_manifest_creation(
    source: str,
    fixture: str,
    old: str,
    spoof: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / fixture
    path.write_text((FIXTURES / fixture).read_text().replace(old, spoof), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match registered version"):
        _ingest(source, path, tmp_path / "cache")


def test_release_date_coherence_is_enforced(tmp_path: Path) -> None:
    bad = tmp_path / "synpuf.csv"
    bad.write_text(
        (FIXTURES / "synpuf.csv").read_text().replace(
            "2009-01-02,2009-01-05", "2012-01-02,2012-01-05", 1
        ),
        encoding="utf-8",
    )

    result = ingest_synpuf(bad, cache_dir=tmp_path / "cache")
    reasons = set(result.quarantine[0].reasons)

    assert "service_from_date:outside_release" in reasons
    assert "service_through_date:outside_release" in reasons
    assert "year:date_mismatch" in reasons


def test_csv_shape_errors_quarantine_only_the_bad_row(tmp_path: Path) -> None:
    malformed = tmp_path / "meps.csv"
    header, first, second = (FIXTURES / "meps.csv").read_text().splitlines()
    malformed.write_text(f"{header}\n{first},EXTRA\n{second}\n", encoding="utf-8")

    result = ingest_meps(malformed, cache_dir=tmp_path / "cache")

    assert len(result.valid) == 1
    assert result.quarantine[0].reasons == ("csv:extra_values",)


def test_meps_survey_sentinel_is_preserved_as_a_nonpositive_proxy_code(
    tmp_path: Path,
) -> None:
    path = tmp_path / "meps-sentinel.csv"
    path.write_text(
        (FIXTURES / "meps.csv").read_text().replace(",1,145.25,", ",-1,145.25,", 1),
        encoding="utf-8",
    )
    result = ingest_meps(path, cache_dir=tmp_path / "cache")
    assert result.valid[0]["kidney_problem_proxy"] == -1


def test_documented_code_domains_reject_invalid_values(tmp_path: Path) -> None:
    nhanes = tmp_path / "nhanes.csv"
    nhanes.write_text(
        (FIXTURES / "nhanes.csv").read_text().replace("Non-Hispanic White", "Martian", 1),
        encoding="utf-8",
    )
    partd = tmp_path / "partd.csv"
    partd.write_text(
        (FIXTURES / "partd.csv").read_text().replace(",PA,", ",ZZ,", 1),
        encoding="utf-8",
    )
    synpuf = tmp_path / "synpuf.csv"
    synpuf.write_text(
        (FIXTURES / "synpuf.csv")
        .read_text()
        .replace(",5853,P100,", ",? ,bad-provider!,", 1),
        encoding="utf-8",
    )

    assert "race_ethnicity:invalid_code" in ingest_nhanes(
        nhanes, cache_dir=tmp_path / "cache1"
    ).quarantine[0].reasons
    assert "provider_state:invalid_code" in ingest_partd(
        partd, cache_dir=tmp_path / "cache2"
    ).quarantine[0].reasons
    synpuf_reasons = ingest_synpuf(synpuf, cache_dir=tmp_path / "cache4").quarantine[0].reasons
    assert "diagnosis_code:invalid_code" in synpuf_reasons
    assert "provider_id:invalid_code" in synpuf_reasons


def test_trials_require_exact_query_and_strict_nested_types(tmp_path: Path) -> None:
    document = json.loads((FIXTURES / "clinicaltrials.json").read_text())
    document["snapshot_metadata"]["query"] = "kidney"
    with (tmp_path / "wrong-query.json").open("w", encoding="utf-8") as handle:
        json.dump(document, handle)
    with pytest.raises(ValueError, match="exact documented CKD query"):
        ingest_trials(tmp_path / "wrong-query.json", cache_dir=tmp_path / "cache1")

    for index, invalid_value in enumerate((True, 12, [], {})):
        typed_document = json.loads((FIXTURES / "clinicaltrials.json").read_text())
        typed_document["studies"][0]["protocolSection"]["identificationModule"][
            "briefTitle"
        ] = invalid_value
        path = tmp_path / f"bad-type-{index}.json"
        with path.open("w", encoding="utf-8") as handle:
            json.dump(typed_document, handle)

        result = ingest_trials(path, cache_dir=tmp_path / f"cache-{index}")

        assert not result.valid
        assert "brief_title:invalid_type" in result.quarantine[0].reasons


@pytest.mark.parametrize(
    ("module", "field", "reason"),
    [
        ("armsInterventionsModule", "interventions", "intervention:missing_sentinel"),
        ("contactsLocationsModule", "locations", "country:missing_sentinel"),
    ],
)
def test_trial_nested_blank_values_are_quarantined(
    module: str, field: str, reason: str, tmp_path: Path
) -> None:
    document = json.loads((FIXTURES / "clinicaltrials.json").read_text())
    item_key = "name" if field == "interventions" else "country"
    document["studies"][0]["protocolSection"][module][field][0][item_key] = "   "
    path = tmp_path / f"blank-{field}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(document, handle)

    result = ingest_trials(path, cache_dir=tmp_path / f"cache-{field}")

    assert not result.valid
    assert reason in result.quarantine[0].reasons


def test_malformed_trial_is_quarantined_without_aborting_valid_study(tmp_path: Path) -> None:
    document = json.loads((FIXTURES / "clinicaltrials.json").read_text())
    document["studies"].insert(0, {"protocolSection": []})
    path = tmp_path / "trials.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(document, handle)

    result = ingest_trials(path, cache_dir=tmp_path / "cache")

    assert len(result.valid) == 1
    assert result.quarantine[0].reasons == ("protocolSection:invalid_type",)


def test_trial_snapshot_cannot_predate_study_update(tmp_path: Path) -> None:
    document = json.loads((FIXTURES / "clinicaltrials.json").read_text())
    document["snapshot_metadata"]["retrieved_at"] = "2026-09-01T12:00:00Z"
    path = tmp_path / "trials.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(document, handle)

    result = ingest_trials(path, cache_dir=tmp_path / "cache")

    assert "last_update_date:after_snapshot" in result.quarantine[0].reasons


def _write_zip(path: Path, member: str, content: str) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, content)


def test_native_partd_zip_columns_are_normalized(tmp_path: Path) -> None:
    path = tmp_path / "Medicare_Part_D_2024.zip"
    _write_zip(
        path,
        "partd_2024.csv",
        "Prscrbr_NPI,Prscrbr_State_Abrvtn,Brnd_Name,Gnrc_Name,Tot_Clms,"
        "Tot_30day_Fills,Tot_Drug_Cst\n1234567890,DC,JARDIANCE,empagliflozin,12,13,999.50\n",
    )

    result = ingest_partd(path, cache_dir=tmp_path / "cache")

    assert result.valid[0]["provider_state"] == "DC"
    assert result.valid[0]["year"] == 2024


def test_extensionless_download_is_detected_from_zip_signature(tmp_path: Path) -> None:
    path = tmp_path / "Medicare_Part_D_2024.download"
    _write_zip(
        path,
        "partd_2024.csv",
        "Prscrbr_NPI,Prscrbr_State_Abrvtn,Brnd_Name,Gnrc_Name,Tot_Clms,"
        "Tot_30day_Fills,Tot_Drug_Cst\n1234567890,DC,JARDIANCE,empagliflozin,12,13,999.50\n",
    )

    result = ingest_partd(path, cache_dir=tmp_path / "cache")

    assert result.valid[0]["total_claim_count"] == 12
    assert result.manifest.cache_path is not None
    assert result.manifest.cache_path.endswith(".zip")


def test_nhanes_xpt_boundary_dispatches_native_normalization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "joined_nhanes_2017_2018.xpt"
    path.write_bytes(b"representative-xpt-boundary")
    rows = [dict(row) for row in ingest_nhanes(FIXTURES / "nhanes.csv", cache_dir=None).valid]
    rows_as_text = [
        {key: str(value) for key, value in row.items() if key != "evidence_type"}
        for row in rows
    ]
    monkeypatch.setattr(
        "ckd_intelligence.ingestion.nhanes._xpt_rows", lambda _payload: rows_as_text
    )

    result = ingest_nhanes(path, cache_dir=tmp_path / "cache")

    assert len(result.valid) == 2
    assert result.manifest.version == "2017-2018"


class _DecodedXptFrame:
    columns = {
        "SEQN", "RIDAGEYR", "RIAGENDR", "RIDRETH3", "LBXSCR", "URXUMA",
        "URXUCR", "WTMEC2YR", "SDMVSTRA", "SDMVPSU",
    }

    def to_dict(self, *, orient: str) -> list[dict[str, float]]:
        assert orient == "records"
        base = {
            "RIDAGEYR": 65.0,
            "RIAGENDR": 2.0,
            "RIDRETH3": 3.0,
            "LBXSCR": 1.1,
            "URXUMA": 35.0,
            "URXUCR": 100.0,
            "WTMEC2YR": 5000.0,
            "SDMVSTRA": 12.0,
            "SDMVPSU": 1.0,
        }
        return [{**base, "SEQN": float("nan")}, {**base, "SEQN": 1002.0}]


class _DecodedXptPandas:
    @staticmethod
    def read_sas(_payload: BytesIO, *, format: str) -> _DecodedXptFrame:
        assert format == "xport"
        return _DecodedXptFrame()


def test_decoded_xpt_missing_seqn_quarantines_only_bad_participant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "nhanes_2017_2018.xpt"
    path.write_bytes(b"simulated-xpt-container")
    monkeypatch.setattr(
        "ckd_intelligence.ingestion.nhanes._pandas", lambda: _DecodedXptPandas()
    )

    result = ingest_nhanes(path, cache_dir=tmp_path / "cache")

    assert result.valid[0]["respondent_id"] == "1002"
    assert len(result.valid) == 1
    assert len(result.quarantine) == 1
    assert "respondent_id:missing_sentinel" in result.quarantine[0].reasons
    assert "respondent_id:invalid_identifier" in result.quarantine[0].reasons
    assert "nan" not in result.quarantine[0].raw_record.values()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_native_nonfinite_scalars_never_become_nan_or_inf_strings(value: float) -> None:
    assert native_scalar_text(value) == ""


def test_nhanes_native_xpt_bundle_dispatches_three_component_join(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "nhanes_2017_2018.zip"
    _write_zip(path, "placeholder.csv", "not used")
    rows = [dict(row) for row in ingest_nhanes(FIXTURES / "nhanes.csv", cache_dir=None).valid]
    rows_as_text = [
        {key: str(value) for key, value in row.items() if key != "evidence_type"}
        for row in rows
    ]
    monkeypatch.setattr(
        "ckd_intelligence.ingestion.nhanes._xpt_bundle_rows",
        lambda _payload: rows_as_text,
    )

    result = ingest_nhanes(path, cache_dir=tmp_path / "cache")

    assert len(result.valid) == 2


def test_meps_xpt_boundary_dispatches_hc243_person_year_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "h243.xpt"
    path.write_bytes(b"representative-xpt-boundary")
    native = [
        {
            "source_release": "HC-243-2022",
            "person_id": "P1",
            "year": "2022",
            "dcs_eligible": "1",
            "diabetes_reported": "1",
            "kidney_problem_proxy": "1",
            "total_expenditure_usd": "120.0",
            "office_visits": "1",
            "outpatient_visits": "0",
            "emergency_visits": "0",
            "inpatient_stays": "0",
            "prescription_medicines": "2",
            "person_weight": "5000.0",
            "proxy_weight": "5000.0",
            "variance_stratum": "12",
            "variance_psu": "1",
        }
    ]
    monkeypatch.setattr(
        "ckd_intelligence.ingestion.meps._native_meps_rows", lambda _payload: native
    )

    result = ingest_meps(path, cache_dir=tmp_path / "cache")

    assert result.valid[0]["total_expenditure_usd"] == 120.0
    assert result.manifest.version == "HC-243-2022"


def test_native_synpuf_zip_columns_are_normalized(tmp_path: Path) -> None:
    path = tmp_path / "DE1_0_2008_to_2010_Inpatient_Claims.zip"
    _write_zip(
        path,
        "claims.csv",
        "DESYNPUF_ID,CLM_ID,CLM_FROM_DT,CLM_THRU_DT,ADMTNG_ICD9_DGNS_CD,"
        "PRVDR_NUM,CLM_PMT_AMT\nB1,C1,20090102,20090105,5853,P100,1420.50\n",
    )

    result = ingest_synpuf(path, cache_dir=tmp_path / "cache")

    assert result.valid[0]["claim_type"] == "inpatient"
    assert result.valid[0]["service_from_date"] == "2009-01-02"


class _RedirectResponse:
    headers = {"Content-Length": "2"}

    def __enter__(self) -> _RedirectResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        return b"{}"

    def geturl(self) -> str:
        return "http://unsafe.example/final.json"


class _HttpsRedirectResponse(_RedirectResponse):
    def __init__(self, payload: bytes) -> None:
        self._stream = BytesIO(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return "https://clinicaltrials.gov/api/intake/snapshot.json"


def test_redirect_to_non_https_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ckd_intelligence.ingestion._common.urlopen",
        lambda *_a, **_k: _RedirectResponse(),
    )

    with pytest.raises(ValueError, match="redirected to a non-HTTPS"):
        ingest_trials("https://clinicaltrials.gov/api/v2/studies", cache_dir=tmp_path)


def test_manifest_records_requested_and_final_https_urls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = (FIXTURES / "clinicaltrials.json").read_bytes()
    monkeypatch.setattr(
        "ckd_intelligence.ingestion._common.urlopen",
        lambda *_a, **_k: _HttpsRedirectResponse(payload),
    )
    requested = "https://clinicaltrials.gov/api/v2/studies?query.cond=CKD"

    result = ingest_trials(requested, cache_dir=tmp_path)

    assert result.manifest.requested_source_uri == requested
    assert result.manifest.source_uri == "https://clinicaltrials.gov/api/intake/snapshot.json"
