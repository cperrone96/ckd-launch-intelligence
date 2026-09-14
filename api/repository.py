from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from pydantic import TypeAdapter, ValidationError

from ckd_intelligence.journeys.synpuf import validate_synpuf_fixture_manifest

from .schemas import (
    MEPSItem,
    ModelSet,
    PartDItem,
    PerformanceComparison,
    PopulationEstimateItem,
    TrialItem,
    WaterfallItem,
)


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


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    """Canonical provenance contract for one API artifact."""

    source: str
    release: str
    source_manifest: str | None = None


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
_ARTIFACT_CONTRACTS: dict[str, ArtifactContract] = {
    "patient_need": ArtifactContract(
        source="CDC/NCHS NHANES",
        release="2017-2018",
        source_manifest="data/manifests/nhanes-2017-2018-patient-need.json",
    ),
    "patient_finding": ArtifactContract(
        source="CDC/NCHS NHANES",
        release="2017-2018",
        source_manifest="data/manifests/nhanes-2017-2018-patient-need.json",
    ),
    "meps": ArtifactContract(source="MEPS / AHRQ", release="HC-243-2022"),
    "partd": ArtifactContract(
        source="CMS Medicare Part D Prescribers by Provider and Drug", release="2024"
    ),
    "trials": ArtifactContract(source="ClinicalTrials.gov", release="api-v2"),
}
_EXPECTED_EVIDENCE_TYPE = "public_observed"
_TRIAL_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "geography": ("country",),
    "status": ("overall_status",),
    "sponsor": ("sponsor",),
    "intervention": ("intervention",),
    "change_over_time": ("update_year",),
}
_ALLOWED_SOURCE_MANIFESTS = frozenset(
    contract.source_manifest
    for contract in _ARTIFACT_CONTRACTS.values()
    if contract.source_manifest is not None
)
_REQUIRED_KEYS: dict[str, frozenset[str]] = {
    "patient_need": frozenset({"waterfall", "estimates", "evidence_type", "limitations"}),
    "patient_finding": frozenset(
        {
            "analysis_population",
            "outcome",
            "artifact_schema",
            "models",
            "subgroups",
            "cohort_sensitivity",
            "paired_differences",
            "limitations",
            "selected_model",
            "selected_threshold",
            "selection_policy",
            "development_capacity",
            "threshold_capacity",
            "holdout_prevalence",
            "holdout_n",
            "features",
            "split",
            "performance_interpretation",
            "intended_use",
            "scorer",
            "evidence_type",
            "source_provenance",
        }
    ),
    "meps": frozenset({"estimates", "evidence_type", "limitations"}),
    "partd": frozenset({"aggregates", "evidence_type", "limitations"}),
    "trials": frozenset(
        {
            "geography",
            "intervention",
            "phase_or_type",
            "change_over_time",
            "status",
            "sponsor",
            "evidence_type",
            "limitations",
        }
    ),
}


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
        if separator != "  " or filename not in {f"{name}\n" for name in expected_names}:
            raise ArtifactIntegrityError("artifact checksum is invalid")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ArtifactIntegrityError("artifact checksum is invalid")
        if digest != computed:
            raise ArtifactIntegrityError("artifact checksum does not match artifact")
        return computed

    @staticmethod
    def _validate_payload(
        key: str, payload: object, contract: ArtifactContract
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ArtifactIntegrityError("artifact JSON must be an object")
        required = _REQUIRED_KEYS[key]
        if not required.issubset(payload):
            raise ArtifactIntegrityError("artifact required schema is incomplete")
        if key not in {"patient_need", "patient_finding"} and any(
            not isinstance(payload.get(field), str) or not payload[field].strip()
            for field in ("source", "release")
        ):
            raise ArtifactIntegrityError("artifact source metadata is invalid")
        evidence_type = payload.get("evidence_type")
        if evidence_type != _EXPECTED_EVIDENCE_TYPE:
            raise ArtifactIntegrityError("artifact evidence classification is invalid")
        limitations = payload.get("limitations")
        if isinstance(limitations, list):
            if not limitations or not all(
                isinstance(item, str) and item.strip() for item in limitations
            ):
                raise ArtifactIntegrityError("artifact limitations are invalid")
        elif isinstance(limitations, dict):
            if not limitations or not all(
                isinstance(item, str) and item.strip() for item in limitations.values()
            ):
                raise ArtifactIntegrityError("artifact limitations are invalid")
        else:
            raise ArtifactIntegrityError("artifact limitations are invalid")
        list_fields = {
            "patient_need": ("waterfall",),
            "meps": ("estimates",),
            "partd": ("aggregates", "dictionary"),
            "trials": (
                "geography",
                "intervention",
                "phase_or_type",
                "change_over_time",
                "status",
                "sponsor",
            ),
        }.get(key, ())
        for field in list_fields:
            value = payload.get(field)
            if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                raise ArtifactIntegrityError("artifact list schema is invalid")
        if key == "patient_need":
            estimates = payload.get("estimates")
            if not isinstance(estimates, dict) or not all(
                isinstance(item, dict) for item in estimates.values()
            ):
                raise ArtifactIntegrityError("artifact estimate schema is invalid")
        if key == "patient_finding":
            source = payload.get("source")
            provenance = payload.get("source_provenance")
            if (
                not isinstance(source, str)
                or contract.source not in source
                or contract.release not in source
                or not isinstance(provenance, dict)
                or provenance.get("source") != contract.source
                or provenance.get("release") != contract.release
                or provenance.get("path") != contract.source_manifest
                or provenance.get("evidence_type") != _EXPECTED_EVIDENCE_TYPE
            ):
                raise ArtifactIntegrityError("artifact payload provenance is invalid")
            models = payload.get("models")
            subgroups = payload.get("subgroups")
            if not isinstance(models, dict) or not models or not all(
                isinstance(item, dict) for item in models.values()
            ):
                raise ArtifactIntegrityError("artifact model schema is invalid")
            if not isinstance(subgroups, dict) or not subgroups or not all(
                isinstance(item, list) and all(isinstance(row, dict) for row in item)
                for item in subgroups.values()
            ):
                raise ArtifactIntegrityError("artifact subgroup schema is invalid")
        try:
            if key == "patient_need":
                TypeAdapter(list[WaterfallItem]).validate_python(payload["waterfall"])
                TypeAdapter(
                    list[PopulationEstimateItem]
                ).validate_python(
                    [{"key": row_key, **row} for row_key, row in payload["estimates"].items()]
                )
            elif key == "meps":
                TypeAdapter(list[MEPSItem]).validate_python(payload["estimates"])
            elif key == "partd":
                TypeAdapter(list[PartDItem]).validate_python(payload["aggregates"])
            elif key == "trials":
                for field in (
                    "geography",
                    "intervention",
                    "phase_or_type",
                    "change_over_time",
                    "status",
                    "sponsor",
                ):
                    TypeAdapter(list[TrialItem]).validate_python(payload[field])
                    required_fields = _TRIAL_REQUIRED_FIELDS.get(field, ())
                    for row in payload[field]:
                        if any(
                            field_name not in row
                            or row[field_name] is None
                            or (isinstance(row[field_name], str) and not row[field_name].strip())
                            for field_name in required_fields
                        ):
                            raise ArtifactIntegrityError(
                                f"trial {field} dimension is missing its defining field"
                            )
                for row in payload["phase_or_type"]:
                    if not (
                        (row.get("phase") is not None and str(row["phase"]).strip())
                        or (row.get("study_type") is not None and str(row["study_type"]).strip())
                    ):
                        raise ArtifactIntegrityError(
                            "trial phase_or_type dimension is missing its defining field"
                        )
            elif key == "patient_finding":
                comparison_keys = (
                    "artifact_schema",
                    "analysis_population",
                    "outcome",
                    "selected_model",
                    "selection_policy",
                    "selected_threshold",
                    "threshold_capacity",
                    "development_capacity",
                    "holdout_prevalence",
                    "holdout_n",
                    "features",
                    "split",
                    "models",
                    "subgroups",
                    "cohort_sensitivity",
                    "paired_differences",
                    "performance_interpretation",
                    "intended_use",
                    "limitations",
                )
                PerformanceComparison.model_validate(
                    {field: payload[field] for field in comparison_keys}
                )
                ModelSet.model_validate(payload["models"])
        except (ValidationError, TypeError, KeyError) as error:
            raise ArtifactIntegrityError("artifact member schema is invalid") from error
        return cast(dict[str, Any], payload)

    @staticmethod
    def _validate_source_manifest(
        source_manifest: object, contract: ArtifactContract, path: Path
    ) -> None:
        if source_manifest != contract.source_manifest:
            raise ArtifactIntegrityError("artifact source manifest semantics are invalid")
        try:
            source_obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError) as error:
            raise ArtifactIntegrityError("source manifest is unreadable") from error
        if not isinstance(source_obj, dict):
            raise ArtifactIntegrityError("source manifest JSON must be an object")
        if (
            source_obj.get("source") != contract.source
            or source_obj.get("release") != contract.release
        ):
            raise ArtifactIntegrityError("source manifest provenance is invalid")
        files = source_obj.get("files")
        if not isinstance(files, list) or not files:
            raise ArtifactIntegrityError("source manifest files are invalid")
        names: set[str] = set()
        for item in files:
            if not isinstance(item, dict):
                raise ArtifactIntegrityError("source manifest file entry is invalid")
            name = item.get("name")
            url = item.get("url")
            digest = item.get("sha256")
            size = item.get("bytes")
            parsed = urlparse(url) if isinstance(url, str) else None
            if (
                not isinstance(name, str)
                or not name.strip()
                or name in names
                or Path(name).name != name
                or parsed is None
                or parsed.scheme != "https"
                or not parsed.netloc
                or not isinstance(digest, str)
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size <= 0
            ):
                raise ArtifactIntegrityError("source manifest file entry is invalid")
            names.add(name)

    def load_json(self, key: str) -> Artifact:
        if key not in _ARTIFACTS:
            raise ArtifactIntegrityError("artifact is not allowlisted")
        name, manifest_name = _ARTIFACTS[key]
        contract = _ARTIFACT_CONTRACTS[key]
        path = (self.data_root / "processed" / name).resolve()
        checksum = path.with_suffix(".sha256")
        manifest_path = (self.data_root / "manifests" / manifest_name).resolve()
        try:
            if self.data_root not in path.parents or self.data_root not in manifest_path.parents:
                raise ArtifactIntegrityError("artifact path is outside the data root")
            digest = self._verify_checksum(path, checksum)
            payload = self._validate_payload(
                key, json.loads(path.read_text(encoding="utf-8")), contract
            )
            manifest_obj = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest_obj, dict):
                raise ArtifactIntegrityError("artifact manifest JSON must be an object")
            manifest = cast(dict[str, Any], manifest_obj)
        except ArtifactIntegrityError:
            raise
        except (OSError, json.JSONDecodeError, TypeError) as error:
            raise ArtifactIntegrityError("artifact or manifest is unreadable") from error
        required_manifest_fields = (
            "source",
            "release",
            "evidence_type",
            "artifact_path",
            "artifact_sha256",
        )
        if any(
            not isinstance(manifest.get(field), str) or not str(manifest[field]).strip()
            for field in required_manifest_fields
        ):
            raise ArtifactIntegrityError("artifact manifest schema is incomplete")
        if manifest["evidence_type"] != _EXPECTED_EVIDENCE_TYPE:
            raise ArtifactIntegrityError("artifact manifest evidence classification is invalid")
        if manifest["source"] != contract.source or manifest["release"] != contract.release:
            raise ArtifactIntegrityError("artifact manifest provenance is invalid")
        source_manifest = manifest.get("source_manifest")
        if contract.source_manifest is None:
            if "source_manifest" in manifest:
                raise ArtifactIntegrityError("artifact source manifest semantics are invalid")
        elif source_manifest not in _ALLOWED_SOURCE_MANIFESTS:
            raise ArtifactIntegrityError("artifact source manifest is required")
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
        if key == "patient_need":
            if (
                payload.get("source_release") != contract.release
                or payload.get("source_manifest") != contract.source_manifest
            ):
                raise ArtifactIntegrityError("artifact payload provenance is invalid")
        elif (
            (
                key == "patient_finding"
                and (
                    contract.source not in str(payload.get("source", ""))
                    or contract.release not in str(payload.get("source", ""))
                )
            )
            or (
                key not in {"patient_finding"}
                and (
                    payload.get("source") != contract.source
                    or payload.get("release") != contract.release
                )
            )
        ):
            raise ArtifactIntegrityError("artifact payload provenance is invalid")
        if contract.source_manifest is not None:
            source_path = (self.data_root.parent / contract.source_manifest).resolve()
            expected_source_path = self.data_root.parent / contract.source_manifest
            if source_path != expected_source_path or not source_path.is_file():
                raise ArtifactIntegrityError("source manifest is unavailable")
            self._validate_source_manifest(source_manifest, contract, source_path)
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
