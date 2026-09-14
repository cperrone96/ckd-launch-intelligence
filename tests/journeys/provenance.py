"""Test-side provenance gate for the DE-SynPUF journey fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pandas as pd

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "data" / "manifests" / "synpuf-journeys-fixture.json"
FIXTURE = ROOT / "data" / "fixtures" / "synpuf_journeys.csv"
EXPECTED_FIXTURE_PATH = "data/fixtures/synpuf_journeys.csv"


def _validate_manifest(manifest_path: Path, fixture_path: Path) -> dict[str, Any]:
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
    assert manifest["fixture_path"] == EXPECTED_FIXTURE_PATH, "fixture_path is wrong"
    assert manifest["evidence_type"] == "public_synthetic", "evidence_type is wrong"
    assert manifest["fixture_kind"] == "fixture_only", "fixture_kind is wrong"
    assert manifest["source_rows_are_official"] is False, "source_rows_are_official must be false"
    assert manifest["no_cross_source_join"] is True, "no_cross_source_join must be true"
    assert fixture_path.exists(), fixture_path
    digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert manifest["fixture_sha256"] == digest, "fixture_sha256 is stale"
    return manifest


def load_verified_synpuf_fixture(
    manifest_path: Path = MANIFEST,
    fixture_path: Path = FIXTURE,
) -> pd.DataFrame:
    """Parse and verify the manifest before reading any journey fixture bytes."""

    _validate_manifest(manifest_path, fixture_path)
    return pd.read_csv(fixture_path)
