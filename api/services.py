from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ckd_intelligence.journeys.synpuf import build_journey_output
from ckd_intelligence.modeling.patient_finding import FeatureValidationError, LogisticScorer

from .repository import ArtifactRepository


class APIValidationError(ValueError):
    def __init__(self, message: str, *, code: str = "invalid_request") -> None:
        super().__init__(message)
        self.code = code


def paginate(items: list[dict[str, Any]], page: int, page_size: int) -> dict[str, Any]:
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "pagination": {"page": page, "page_size": page_size, "total": len(items)},
    }


class CKDAnalyticsService:
    def __init__(self, repository: ArtifactRepository | None = None) -> None:
        self.repository = repository or ArtifactRepository()

    @staticmethod
    def _evidence(
        artifact: Any, *, population: str, grain: str, window: str, limitations: list[str]
    ) -> dict[str, Any]:
        return {
            "evidence_type": artifact.payload.get("evidence_type", "public_observed"),
            "source": artifact.payload.get(
                "source", artifact.manifest.get("source", "public source")
            ),
            "release": artifact.payload.get(
                "release", artifact.manifest.get("release", "unspecified")
            ),
            "source_population": population,
            "grain": grain,
            "source_date_or_window": window,
            "provenance": {
                "artifact": str(artifact.path.relative_to(self_path(artifact.path.parents[1]))),
                "sha256": artifact.digest,
                "manifest": str(
                    artifact.manifest_path.relative_to(self_path(artifact.path.parents[1]))
                ),
                "source_manifest": artifact.manifest.get("source_manifest"),
            },
            "limitations": [item for item in limitations if item.strip()],
            "join_policy": "Source-specific aggregate only; no patient-level or cross-source join.",
        }

    def evidence(self, key: str, **kwargs: Any) -> dict[str, Any]:
        artifact = self.repository.load_json(key)
        caller_limitations = kwargs.pop("limitations", None)
        limitations = (
            caller_limitations
            if caller_limitations is not None
            else artifact.payload.get("limitations", [])
        )
        if isinstance(limitations, dict):
            limitations = [str(value) for value in limitations.values()]
        if not isinstance(limitations, list):
            limitations = [str(limitations)]
        return self._evidence(artifact, limitations=limitations, **kwargs)

    def sources(self) -> dict[str, Any]:
        records = []
        for key in ("patient_need", "patient_finding", "meps", "partd", "trials"):
            artifact = self.repository.load_json(key)
            records.append(
                {
                    "key": key,
                    "source": artifact.payload.get("source", artifact.manifest.get("source")),
                    "release": artifact.payload.get("release", artifact.manifest.get("release")),
                    "evidence_type": artifact.payload.get("evidence_type", "public_observed"),
                    "artifact_sha256": artifact.digest,
                }
            )
        return {"sources": records}

    def collection(
        self,
        key: str,
        rows_key: str,
        page: int,
        page_size: int,
        *,
        filters: dict[str, str] | None = None,
        population: str,
        grain: str,
        window: str,
    ) -> dict[str, Any]:
        artifact = self.repository.load_json(key)
        rows = artifact.payload.get(rows_key, [])
        if isinstance(rows, dict):
            if not all(isinstance(value, dict) for value in rows.values()):
                raise APIValidationError(
                    "artifact collection is invalid", code="artifact_schema_error"
                )
            items = [{"key": str(row_key), **value} for row_key, value in rows.items()]
        elif isinstance(rows, list):
            if not all(isinstance(row, dict) for row in rows):
                raise APIValidationError(
                    "artifact collection is invalid", code="artifact_schema_error"
                )
            items = list(rows)
        else:
            raise APIValidationError("artifact collection is invalid", code="artifact_schema_error")
        for field, value in (filters or {}).items():
            items = [row for row in items if str(row.get(field, "")) == value]
        result = paginate(items, page, page_size)
        result["evidence"] = self.evidence(key, population=population, grain=grain, window=window)
        return result

    def complete_collection(
        self,
        key: str,
        rows_key: str,
        *,
        population: str,
        grain: str,
        window: str,
    ) -> dict[str, Any]:
        result = self.collection(
            key,
            rows_key,
            1,
            100,
            population=population,
            grain=grain,
            window=window,
        )
        total = result["pagination"]["total"]
        if len(result["items"]) != total:
            artifact = self.repository.load_json(key)
            rows = artifact.payload[rows_key]
            if isinstance(rows, dict):
                items = [{"key": str(row_key), **value} for row_key, value in rows.items()]
            elif isinstance(rows, list):
                items = list(rows)
            else:
                raise APIValidationError(
                    "artifact collection is invalid", code="artifact_schema_error"
                )
            result["items"] = items
        result["total"] = len(result["items"])
        result["pagination_complete"] = len(result["items"]) == result["total"]
        return result

    def score(self, record: dict[str, Any]) -> dict[str, Any]:
        artifact = self.repository.load_json("patient_finding")
        scorer_payload = artifact.payload.get("scorer")
        if not isinstance(scorer_payload, dict):
            raise APIValidationError("scorer artifact is invalid", code="artifact_schema_error")
        try:
            scorer = LogisticScorer.from_dict(scorer_payload)
            probability = scorer.score_one(record)
        except (FeatureValidationError, ValueError) as error:
            raise APIValidationError(str(error), code="scoring_input_error") from error
        threshold = float(artifact.payload.get("selected_threshold", 0.5))
        limitations = [str(x) for x in artifact.payload.get("limitations", [])]
        return {
            "probability": probability,
            "threshold": threshold,
            "selected": probability >= threshold,
            "intended_use": "educational screening-opportunity demonstration",
            "interpretation": (
                "Population-analytics score for an educational demonstration; it is not "
                "a clinical conclusion or care recommendation."
            ),
            "evidence": self.evidence(
                "patient_finding",
                population="NHANES 2017-2018 analytic population",
                grain="person-level model contract; no row-level output",
                window="2017-2018",
                limitations=limitations,
            ),
            "limitations": limitations,
        }

    def performance(self) -> dict[str, Any]:
        artifact = self.repository.load_json("patient_finding")
        comparison = {
            key: artifact.payload[key]
            for key in (
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
            if key in artifact.payload
        }
        return {
            "comparison": comparison,
            "evidence": self.evidence(
                "patient_finding",
                population="NHANES 2017-2018 analytic population",
                grain="model comparison aggregate",
                window="2017-2018",
            ),
        }

    def opportunity(self) -> dict[str, Any]:
        prescribing = self.complete_collection(
                "partd",
                "aggregates",
                population="Medicare Part D prescriber-drug aggregates",
                grain="provider-drug-state aggregate",
                window="2024",
            )
        trials = self.complete_collection(
                "trials",
                "geography",
                population="registered CKD studies",
                grain="registered study-country mention",
                window="API release snapshot",
            )
        panels = {
            "prescribing_provider_state": {
                "items": prescribing["items"],
                "total": prescribing["total"],
                "pagination_complete": prescribing["pagination_complete"],
                "evidence": prescribing["evidence"],
            },
            "trials_country": {
                "items": trials["items"],
                "total": trials["total"],
                "pagination_complete": trials["pagination_complete"],
                "evidence": trials["evidence"],
            },
        }
        evidence = [
            self.evidence(
                "partd",
                population="Medicare Part D prescriber-drug aggregates",
                grain="provider-drug-state aggregate",
                window="2024",
            ),
            self.evidence(
                "trials",
                population="registered CKD studies",
                grain="registered study-country mention",
                window="API release snapshot",
            ),
        ]
        return {
            "scenario_only": True,
            "source_panels": panels,
            "scenario_rankings": [],
            "limitations": (
                "No composite or state leaderboard is published: sources have incompatible "
                "geographies and time windows. Scenario rankings require explicit compatible "
                "aggregate inputs and are not observed market results."
            ),
            "evidence": evidence,
        }

    def journeys(self) -> dict[str, Any]:
        fixture, manifest = self.repository.load_synpuf()
        claims = pd.read_csv(fixture)
        output = build_journey_output(claims)
        summaries_frame = output.summaries.drop(columns=["synthetic_id"], errors="ignore")
        summaries = json.loads(summaries_frame.to_json(orient="records", date_format="iso"))
        survival = json.loads(output.survival.to_json(orient="records"))
        return {
            "summaries": summaries,
            "survival": survival,
            "rules": {
                "rule_text": output.rules.rule_text,
                "observation_start": output.rules.observation_start.isoformat(),
                "observation_end": output.rules.observation_end.isoformat(),
            },
            "evidence": {
                "evidence_type": "public_synthetic",
                "source": manifest["source"],
                "release": manifest["release"],
                "source_population": "CMS DE-SynPUF handcrafted fixture",
                "grain": "synthetic claim journey summary",
                "source_date_or_window": "2008-2010",
                "provenance": {
                    "artifact": manifest["fixture_path"],
                    "sha256": manifest["fixture_sha256"],
                    "manifest": "data/manifests/synpuf-journeys-fixture.json",
                },
                "limitations": [manifest["limitations"]],
                "join_policy": "Synthetic fixture only; no cross-source join.",
            },
            "limitations": [manifest["limitations"]],
        }


def self_path(path: Path) -> Path:
    """Return the repository's project root for stable provenance paths."""
    for parent in path.parents:
        if (parent / "data").is_dir() and (parent / "src").is_dir():
            return parent
    return path.parents[-1]
