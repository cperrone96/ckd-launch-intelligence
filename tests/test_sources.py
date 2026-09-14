import hashlib
import json
import re
from pathlib import Path

import pytest

from ckd_intelligence.sources import SourceRecord, get_source_registry

FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "source_registry"


def test_every_source_declares_population_grain_and_evidence_type() -> None:
    for source in get_source_registry():
        assert source.population
        assert source.grain
        assert source.evidence_type in {"public_observed", "public_synthetic"}
        assert source.checksum


def test_registry_covers_each_source_family_exactly_once() -> None:
    names = [source.name for source in get_source_registry()]

    assert names == ["nhanes", "meps", "partd", "clinicaltrials", "synpuf"]


def test_only_synpuf_is_public_synthetic() -> None:
    evidence_by_name = {
        source.name: source.evidence_type for source in get_source_registry()
    }

    assert evidence_by_name == {
        "nhanes": "public_observed",
        "meps": "public_observed",
        "partd": "public_observed",
        "clinicaltrials": "public_observed",
        "synpuf": "public_synthetic",
    }


def test_partd_registry_identifies_latest_verified_cms_release() -> None:
    partd = next(source for source in get_source_registry() if source.name == "partd")
    metadata = json.loads((FIXTURE_DIRECTORY / "partd.json").read_text())

    assert partd.version == "2024"
    assert metadata == {
        "family": "partd",
        "manifest_kind": "registry_metadata",
        "dataset_title": "Medicare Part D Prescribers - by Provider and Drug",
        "source_url": (
            "https://data.cms.gov/provider-summary-by-type-of-service/"
            "medicare-part-d-prescribers/"
            "medicare-part-d-prescribers-by-provider-and-drug"
        ),
        "version": "2024",
        "update_frequency": "annually",
        "latest_available_verified_on": "2026-09-11",
        "snapshot_scope": (
            "No source rows; metadata identifies the CMS public-use dataset release."
        ),
    }

def test_registry_is_an_immutable_tuple_of_frozen_records() -> None:
    registry = get_source_registry()

    assert isinstance(registry, tuple)
    with pytest.raises(TypeError):
        registry[0] = registry[0]  # type: ignore[index]
    with pytest.raises(AttributeError):
        registry[0].name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("source", get_source_registry(), ids=lambda item: item.name)
def test_checksum_authenticates_committed_registry_metadata(source: SourceRecord) -> None:
    fixture_bytes = (FIXTURE_DIRECTORY / f"{source.name}.json").read_bytes()
    actual_checksum = hashlib.sha256(fixture_bytes).hexdigest()

    assert re.fullmatch(r"[0-9a-f]{64}", source.checksum)
    assert source.checksum == actual_checksum
