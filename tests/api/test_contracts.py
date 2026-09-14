from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api.main import create_app
from api.repository import ArtifactIntegrityError, ArtifactRepository
from api.services import CKDAnalyticsService


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def score_request() -> dict[str, object]:
    return {
        "age_years": 55,
        "sex": "Female",
        "race_ethnicity": "Non-Hispanic White",
    }


def reseal_artifact(root: Path, artifact_name: str) -> None:
    """Update both integrity declarations after an intentional fixture mutation."""

    artifact = root / "processed" / artifact_name
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (root / "processed" / f"{artifact.stem}.sha256").write_text(
        f"{digest}  data/processed/{artifact_name}\n", encoding="utf-8"
    )
    manifest_path = root / "manifests" / artifact_name
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_sha256"] = digest
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_health_and_exact_routes(client: TestClient) -> None:
    assert client.get("/api/v1/health").json() == {
        "status": "ok",
        "service": "ckd-launch-intelligence",
        "version": "1.0.0",
        "repository": "committed public artifacts only",
        "evidence_boundary": "aggregate; no patient-level cross-source joins",
    }
    paths = set(client.get("/openapi.json").json()["paths"])
    assert paths == {
        "/api/v1/health",
        "/api/v1/sources",
        "/api/v1/cohorts",
        "/api/v1/population-estimates",
        "/api/v1/patient-finding/performance",
        "/api/v1/patient-finding/score",
        "/api/v1/utilization",
        "/api/v1/prescribing",
        "/api/v1/geography/opportunity",
        "/api/v1/trials",
        "/api/v1/journeys/synthetic",
    }


def test_sources_are_strictly_typed_and_all_openapi_objects_forbid_extra_fields(
    client: TestClient,
) -> None:
    sources = client.get("/api/v1/sources")
    assert sources.status_code == 200
    assert len(sources.json()["sources"]) == 5
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert all(
        schema.get("type") != "object" or schema.get("additionalProperties") is False
        for schema in schemas.values()
    )


def test_scoring_response_is_not_diagnostic(
    client: TestClient, score_request: dict[str, object]
) -> None:
    response = client.post("/api/v1/patient-finding/score", json=score_request)
    assert response.status_code == 200
    body = response.json()
    assert body["intended_use"] == "educational screening-opportunity demonstration"
    assert "clinical conclusion" in body["interpretation"]
    assert body["evidence"]["evidence_type"] == "public_observed"
    assert body["limitations"]


@pytest.mark.parametrize("field,value", [("age_years", 999), ("age_years", None)])
def test_scoring_rejects_out_of_range_age(
    client: TestClient, score_request: dict[str, object], field: str, value: object
) -> None:
    score_request[field] = value
    response = client.post("/api/v1/patient-finding/score", json=score_request)
    assert response.status_code == 422
    assert set(response.json()) == {"code", "message", "details"}
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda x: x.update(egfr=30),
        lambda x: x.pop("sex"),
        lambda x: x.update(race_ethnicity="unknown"),
    ],
)
def test_scoring_rejects_leakage_missing_and_unknown(
    client: TestClient, score_request: dict[str, object], mutator: object
) -> None:
    mutator(score_request)  # type: ignore[operator]
    assert client.post("/api/v1/patient-finding/score", json=score_request).status_code == 422


def test_scoring_rejects_nonfinite_and_extra_fields(
    client: TestClient, score_request: dict[str, object]
) -> None:
    score_request["age_years"] = "NaN"
    assert client.post("/api/v1/patient-finding/score", json=score_request).status_code == 422
    score_request["age_years"] = 55
    score_request["egfr"] = 30
    response = client.post("/api/v1/patient-finding/score", json=score_request)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_cohort_waterfall_and_full_model_comparison(client: TestClient) -> None:
    cohort = client.get("/api/v1/cohorts").json()
    assert {row["stage"] for row in cohort["items"]} >= {
        "NHANES 2017-2018 participants",
        "complete eGFR and UACR defining labs",
    }
    performance = client.get("/api/v1/patient-finding/performance")
    assert performance.status_code == 200
    comparison = performance.json()["comparison"]
    assert comparison["selected_model"]
    assert comparison["selected_threshold"] is not None
    assert comparison["models"]
    assert comparison["subgroups"]
    assert comparison["cohort_sensitivity"]
    assert comparison["analysis_population"]
    assert comparison["outcome"]


def test_collection_pagination_and_filters(client: TestClient) -> None:
    response = client.get(
        "/api/v1/prescribing", params={"provider_state": "NY", "page": 1, "page_size": 2}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["page_size"] == 2
    assert len(body["items"]) <= 2
    assert (
        client.get("/api/v1/prescribing", params={"provider_state": "new york"}).status_code == 422
    )
    assert client.get("/api/v1/prescribing", params={"page_size": 101}).status_code == 422
    first = client.get("/api/v1/prescribing", params={"page": 1, "page_size": 1}).json()
    last_page = (first["pagination"]["total"] + 0) // 1
    last = client.get(
        "/api/v1/prescribing", params={"page": max(last_page, 1), "page_size": 1}
    ).json()
    empty = client.get(
        "/api/v1/prescribing", params={"page": first["pagination"]["total"] + 1, "page_size": 1}
    ).json()
    assert first["items"] and last["items"]
    assert empty["items"] == []
    filtered = client.get(
        "/api/v1/prescribing", params={"generic_name": "Finerenone", "page_size": 2}
    )
    assert filtered.status_code == 200
    assert all(row["generic_name"] == "Finerenone" for row in filtered.json()["items"])


def test_opportunity_is_source_specific_and_scenario_safe(client: TestClient) -> None:
    response = client.get("/api/v1/geography/opportunity")
    assert response.status_code == 200
    body = response.json()
    assert body["scenario_only"] is True
    assert body["scenario_rankings"] == []
    assert "source_panels" in body
    assert "composite" in body["limitations"].lower()
    for panel in body["source_panels"].values():
        assert panel["pagination_complete"] is True
        assert panel["total"] == len(panel["items"])


def test_journey_is_synthetic_and_has_no_beneficiary_ids(client: TestClient) -> None:
    response = client.get("/api/v1/journeys/synthetic")
    assert response.status_code == 200
    body = response.json()
    assert body["evidence"]["evidence_type"] == "public_synthetic"
    serialized = json.dumps(body)
    assert "beneficiary_id" not in serialized
    assert body["limitations"]


@pytest.mark.parametrize(
    "dimension",
    ["geography", "intervention", "phase_or_type", "change_over_time", "status", "sponsor"],
)
def test_all_trial_dimensions_are_allowlisted(client: TestClient, dimension: str) -> None:
    response = client.get("/api/v1/trials", params={"dimension": dimension})
    assert response.status_code == 200


def test_serialized_collections_exclude_raw_identifiers(client: TestClient) -> None:
    for path in ("/api/v1/prescribing", "/api/v1/trials", "/api/v1/journeys/synthetic"):
        serialized = json.dumps(client.get(path).json()).lower()
        assert "provider_id" not in serialized
        assert "nct" not in serialized
        assert "beneficiary_id" not in serialized


def test_openapi_is_strict_and_documents_structured_errors(client: TestClient) -> None:
    document = client.get("/openapi.json").json()
    assert document["components"]["schemas"]["ScoringRequest"]["additionalProperties"] is False
    assert document["components"]["schemas"]["ErrorResponse"]["additionalProperties"] is False
    assert "422" in document["paths"]["/api/v1/patient-finding/score"]["post"]["responses"]


def test_not_found_and_method_errors_are_structured(client: TestClient) -> None:
    missing = client.get("/api/v1/nope")
    assert missing.status_code == 404
    assert set(missing.json()) == {"code", "message", "details"}
    method = client.post("/api/v1/health")
    assert method.status_code == 405
    assert set(method.json()) == {"code", "message", "details"}


def test_repository_rejects_tampered_checksum(tmp_path: Path) -> None:
    root = tmp_path / "data"
    processed = root / "processed"
    processed.mkdir(parents=True)
    artifact = processed / "patient_need_summary.json"
    artifact.write_text("{}", encoding="utf-8")
    (processed / "patient_need_summary.sha256").write_text(
        "0" * 64 + "  data/processed/patient_need_summary.json\n", encoding="utf-8"
    )
    with pytest.raises(ArtifactIntegrityError):
        ArtifactRepository(root).load_json("patient_need")


def test_api_fails_closed_on_tampered_committed_artifact(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "data"
    root = tmp_path / "data"
    shutil.copytree(source, root)
    artifact = root / "processed" / "partd_2024_ckd_therapy_landscape.json"
    artifact.write_text(artifact.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    response = TestClient(create_app(CKDAnalyticsService(ArtifactRepository(root)))).get(
        "/api/v1/prescribing"
    )
    assert response.status_code == 503
    assert response.json() == {
        "code": "artifact_integrity_error",
        "message": "A committed analytics artifact failed integrity verification.",
        "details": {},
    }


@pytest.mark.parametrize("replacement", ["[]", "{\"waterfall\": [1]}"])
def test_api_fails_closed_on_non_object_or_invalid_artifact_member(
    tmp_path: Path, replacement: str
) -> None:
    source = Path(__file__).resolve().parents[2] / "data"
    root = tmp_path / "data"
    shutil.copytree(source, root)
    artifact = root / "processed" / "patient_need_summary.json"
    artifact.write_text(replacement, encoding="utf-8")
    reseal_artifact(root, "patient_need_summary.json")
    with pytest.raises(ArtifactIntegrityError):
        ArtifactRepository(root).load_json("patient_need")
    response = TestClient(create_app(CKDAnalyticsService(ArtifactRepository(root)))).get(
        "/api/v1/population-estimates"
    )
    assert response.status_code == 503


def test_api_rejects_manifest_source_namespace_traversal(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "data"
    root = tmp_path / "data"
    shutil.copytree(source, root)
    manifest = root / "manifests" / "patient_need_summary.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["source_manifest"] = "data/manifests/../processed/patient_need_summary.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    response = TestClient(create_app(CKDAnalyticsService(ArtifactRepository(root)))).get(
        "/api/v1/population-estimates"
    )
    assert response.status_code == 503


def test_api_fails_closed_on_tampered_synthetic_manifest(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "data"
    root = tmp_path / "data"
    shutil.copytree(source, root)
    manifest = root / "manifests" / "synpuf-journeys-fixture.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["no_cross_source_join"] = False
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    response = TestClient(create_app(CKDAnalyticsService(ArtifactRepository(root)))).get(
        "/api/v1/journeys/synthetic"
    )
    assert response.status_code == 503


@pytest.mark.parametrize("field", ["artifact_sha256", "artifact_path", "source_manifest"])
def test_api_rejects_missing_or_stale_manifest_metadata(tmp_path: Path, field: str) -> None:
    source = Path(__file__).resolve().parents[2] / "data"
    root = tmp_path / "data"
    shutil.copytree(source, root)
    manifest = root / "manifests" / "patient_need_summary.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    if field == "artifact_sha256":
        payload.pop(field)
    elif field == "artifact_path":
        payload[field] = "data/processed/wrong.json"
    else:
        payload[field] = "data/manifests/missing.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    response = TestClient(create_app(CKDAnalyticsService(ArtifactRepository(root)))).get(
        "/api/v1/population-estimates"
    )
    assert response.status_code == 503


@pytest.mark.parametrize("field", ["source", "release", "evidence_type", "source_manifest"])
def test_api_rejects_incomplete_manifest_metadata(tmp_path: Path, field: str) -> None:
    source = Path(__file__).resolve().parents[2] / "data"
    root = tmp_path / "data"
    shutil.copytree(source, root)
    manifest = root / "manifests" / "patient_need_summary.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload.pop(field)
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    response = TestClient(create_app(CKDAnalyticsService(ArtifactRepository(root)))).get(
        "/api/v1/population-estimates"
    )
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("dimension", "field"),
    [
        ("geography", "country"),
        ("status", "overall_status"),
        ("sponsor", "sponsor"),
        ("intervention", "intervention"),
        ("change_over_time", "update_year"),
    ],
)
def test_trial_dimension_requires_semantic_key(
    tmp_path: Path, dimension: str, field: str
) -> None:
    source = Path(__file__).resolve().parents[2] / "data"
    root = tmp_path / "data"
    shutil.copytree(source, root)
    artifact = root / "processed" / "clinicaltrials_ckd_landscape.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload[dimension][0].pop(field, None)
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    reseal_artifact(root, "clinicaltrials_ckd_landscape.json")
    with pytest.raises(ArtifactIntegrityError, match="defining field"):
        ArtifactRepository(root).load_json("trials")
    response = TestClient(create_app(CKDAnalyticsService(ArtifactRepository(root)))).get(
        "/api/v1/trials", params={"dimension": dimension}
    )
    assert response.status_code == 503


def test_phase_or_type_requires_phase_or_study_type(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[2] / "data"
    root = tmp_path / "data"
    shutil.copytree(source, root)
    artifact = root / "processed" / "clinicaltrials_ckd_landscape.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    payload["phase_or_type"][0].pop("phase", None)
    payload["phase_or_type"][0].pop("study_type", None)
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    reseal_artifact(root, "clinicaltrials_ckd_landscape.json")
    with pytest.raises(ArtifactIntegrityError, match="defining field"):
        ArtifactRepository(root).load_json("trials")
    response = TestClient(create_app(CKDAnalyticsService(ArtifactRepository(root)))).get(
        "/api/v1/trials", params={"dimension": "phase_or_type"}
    )
    assert response.status_code == 503


@pytest.mark.parametrize(
    "checksum_text",
    [
        "0" * 64 + "  data/processed/patient_need_summary.json\n",
        "0" * 64 + "  data/processed/patient_need_summary.json\nextra\n",
        "0" * 64 + "  data/processed/wrong.json\n",
    ],
)
def test_api_rejects_malformed_checksum_sidecars(tmp_path: Path, checksum_text: str) -> None:
    source = Path(__file__).resolve().parents[2] / "data"
    root = tmp_path / "data"
    shutil.copytree(source, root)
    sidecar = root / "processed" / "patient_need_summary.sha256"
    sidecar.write_text(checksum_text, encoding="utf-8")
    response = TestClient(create_app(CKDAnalyticsService(ArtifactRepository(root)))).get(
        "/api/v1/population-estimates"
    )
    assert response.status_code == 503
