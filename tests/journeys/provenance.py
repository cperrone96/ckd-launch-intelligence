"""Test-side provenance gate for the DE-SynPUF journey fixture."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ckd_intelligence.journeys.synpuf import validate_synpuf_fixture_manifest

ROOT = Path(__file__).parents[2]
MANIFEST = ROOT / "data" / "manifests" / "synpuf-journeys-fixture.json"
FIXTURE = ROOT / "data" / "fixtures" / "synpuf_journeys.csv"


def load_verified_synpuf_fixture(
    manifest_path: Path = MANIFEST,
    fixture_path: Path = FIXTURE,
) -> pd.DataFrame:
    """Parse and verify the manifest before reading any journey fixture bytes."""

    validate_synpuf_fixture_manifest(manifest_path, fixture_path)
    return pd.read_csv(fixture_path)
