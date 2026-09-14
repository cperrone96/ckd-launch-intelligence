from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.build_public_landscape as build
from ckd_intelligence.statistics.survey import Estimate


def _estimate() -> Estimate:
    return Estimate(
        point=0.5,
        standard_error=0.1,
        ci_low=0.3,
        ci_high=0.7,
        confidence_level=0.95,
        denominator=2,
        design_observations=2,
        excluded_missing=0,
        sum_weights=2.0,
        strata=1,
        psus=2,
        degrees_freedom=1,
        variance_method="fixture",
        lonely_psu_strategy="certainty",
        source_population="fixture population",
    )


def test_meps_rebuild_preserves_acquisition_metadata_and_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    raw = root / "data/raw/meps/HC-243-2022"
    raw.mkdir(parents=True)
    source_path = raw / "h243dat.zip"
    source_path.write_bytes(b"unchanged HC-243 input")
    rows = [
        {
            "proxy_weight": 1.0,
            "person_weight": 1.0,
            "dcs_eligible": 1,
            "diabetes_reported": 1,
            "kidney_problem_proxy": 1,
            "variance_stratum": 1,
            "variance_psu": 1,
            "office_visits": 1.0,
            "outpatient_visits": 1.0,
            "emergency_visits": 1.0,
            "inpatient_stays": 1.0,
            "prescription_medicines": 1.0,
            "total_expenditure_usd": 1.0,
        },
        {
            **{
                "proxy_weight": 1.0,
                "person_weight": 1.0,
                "dcs_eligible": 1,
                "diabetes_reported": 1,
                "kidney_problem_proxy": 2,
                "variance_stratum": 1,
                "variance_psu": 2,
                "office_visits": 2.0,
                "outpatient_visits": 2.0,
                "emergency_visits": 2.0,
                "inpatient_stays": 2.0,
                "prescription_medicines": 2.0,
                "total_expenditure_usd": 2.0,
            }
        },
    ]
    result = SimpleNamespace(valid=rows, quarantine=())
    estimate = _estimate()
    monkeypatch.setattr(build, "ROOT", root)
    monkeypatch.setattr(build, "MEPS_ZIP", source_path)
    monkeypatch.setattr(build, "ingest_meps", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(build, "weighted_prevalence", lambda *_args, **_kwargs: estimate)
    monkeypatch.setattr(build, "weighted_mean", lambda *_args, **_kwargs: estimate)
    monkeypatch.setattr(build, "_now", lambda: "2026-01-01T00:00:00Z")

    build.build_meps()
    processed = root / "data/processed/meps_hc243_2022_landscape.json"
    manifest = root / "data/manifests/meps_hc243_2022_landscape.json"
    first_artifact = processed.read_bytes()
    first_manifest = manifest.read_bytes()
    first_digest = hashlib.sha256(first_artifact).hexdigest()
    assert json.loads(manifest.read_text(encoding="utf-8"))["artifact_sha256"] == first_digest

    monkeypatch.setattr(build, "_now", lambda: "2026-02-02T00:00:00Z")
    build.build_meps()

    assert processed.read_bytes() == first_artifact
    assert manifest.read_bytes() == first_manifest
