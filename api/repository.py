from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ckd_intelligence.journeys.synpuf import validate_synpuf_fixture_manifest


class ArtifactIntegrityError(RuntimeError):
    """Raised when a committed artifact cannot be verified exactly."""


@dataclass(frozen=True, slots=True)
class Artifact:
    key: str
    path: Path
    manifest_path: Path
    digest: str
    payload: dict[str, Any]
    manifest: dict[str, Any]


_ARTIFACTS: dict[str, tuple[str, str]] = {
    "patient_need": ("patient_need_summary.json", "patient_need_summary.json"),
    "patient_finding": (
        "patient_finding_model_comparison.json",
        "patient_finding_model_comparison.json",
    ),
    "meps": ("meps_hc243_2022_landscape.json", "meps_hc243_2022_landscape.json"),
    "partd": ("partd_2024_ckd_therapy_landscape.json", "partd_2024_ckd_therapy_landscape.json"),
    "trials": ("clinicaltrials_ckd_landscape.json", "clinicaltrials_ckd_landscape.json"),
}
_EXPECTED_EVIDENCE_TYPE = "public_observed"


class ArtifactRepository:
    """Read-only loader for a finite allowlist of committed JSON artifacts."""

    def __init__(self, data_root: Path | None = None) -> None:
        self.data_root = (data_root or Path(__file__).resolve().parents[1] / "data").resolve()

    def _verify_checksum(self, path: Path, checksum: Path) -> str:
        try:
            raw = checksum.read_text(encoding="utf-8")
            digest, separator, filename = raw.partition("  ")
            computed = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise ArtifactIntegrityError("artifact or checksum is unreadable") from error
        expected_names = {path.name, Path("data/processed", path.name).as_posix()}
        if separator != "  " or not any(filename == f"{name}\n" for name in expected_names):
            raise ArtifactIntegrityError("artifact checksum is invalid")
        if digest != computed:
            raise ArtifactIntegrityError("artifact checksum does not match artifact")
        return computed

    def load_json(self, key: str) -> Artifact:
        if key not in _ARTIFACTS:
            raise ArtifactIntegrityError("artifact is not allowlisted")
        name, manifest_name = _ARTIFACTS[key]
        path = (self.data_root / "processed" / name).resolve()
        checksum = path.with_suffix(".sha256")
        manifest_path = (self.data_root / "manifests" / manifest_name).resolve()
        try:
            if self.data_root not in path.parents or self.data_root not in manifest_path.parents:
                raise ArtifactIntegrityError("artifact path is outside the data root")
            digest = self._verify_checksum(path, checksum)
            payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
            manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
        except ArtifactIntegrityError:
            raise
        except (OSError, json.JSONDecodeError, TypeError) as error:
            raise ArtifactIntegrityError("artifact or manifest is unreadable") from error
        declared = manifest.get("artifact_sha256")
        if not isinstance(declared, str) or declared != digest:
            raise ArtifactIntegrityError("artifact manifest digest is stale")
        declared_path = manifest.get("artifact_path")
        if (
            not isinstance(declared_path, str)
            or Path(declared_path).as_posix() != Path("data/processed", name).as_posix()
        ):
            raise ArtifactIntegrityError("artifact manifest path is stale")
        if payload.get("evidence_type") != _EXPECTED_EVIDENCE_TYPE:
            raise ArtifactIntegrityError("artifact evidence classification is invalid")
        manifest_evidence = manifest.get("evidence_type")
        if manifest_evidence is not None and manifest_evidence != _EXPECTED_EVIDENCE_TYPE:
            raise ArtifactIntegrityError("artifact manifest evidence classification is invalid")
        source_manifest = manifest.get("source_manifest")
        if source_manifest is not None:
            if not isinstance(source_manifest, str) or not source_manifest.startswith(
                "data/manifests/"
            ):
                raise ArtifactIntegrityError("source manifest path is invalid")
            source_path = (self.data_root.parent / source_manifest).resolve()
            if self.data_root not in source_path.parents or not source_path.is_file():
                raise ArtifactIntegrityError("source manifest is unavailable")
        return Artifact(key, path, manifest_path, digest, payload, manifest)

    def load_synpuf(self) -> tuple[Path, dict[str, Any]]:
        manifest_path = self.data_root / "manifests" / "synpuf-journeys-fixture.json"
        fixture_path = self.data_root / "fixtures" / "synpuf_journeys.csv"
        try:
            manifest = validate_synpuf_fixture_manifest(manifest_path, fixture_path)
        except (OSError, ValueError) as error:
            raise ArtifactIntegrityError(
                "synthetic journey fixture failed integrity verification"
            ) from error
        return fixture_path, manifest
