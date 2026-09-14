"""Build safe, source-specific public landscape aggregates.

Raw public rows stay under ``data/raw`` (gitignored).  The committed JSON files
contain only aggregate estimates, reconciliations, and provenance.  No person,
beneficiary, NPI, or trial identifier is emitted.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ckd_intelligence.analysis.trials import (
    summarize_trial_composition,
    summarize_trial_geography,
    summarize_trial_status,
    summarize_trial_updates,
)
from ckd_intelligence.ingestion.meps import ingest_meps
from ckd_intelligence.ingestion.trials import ingest_trials
from ckd_intelligence.statistics.survey import weighted_mean, weighted_prevalence

ROOT = Path(__file__).parents[1]
MEPS_ZIP = ROOT / "data/raw/meps/HC-243-2022/h243dat.zip"
CTG_JSON = ROOT / "data/raw/clinicaltrials/ckd-2026-09-11/clinicaltrials-ckd-full.json"
PARTD_DIR = ROOT / "data/raw/partd/2024-ckd-dictionary-v1"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(stem: str, artifact: dict[str, Any], manifest: dict[str, Any]) -> None:
    processed = ROOT / "data/processed"
    manifests = ROOT / "data/manifests"
    processed.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    artifact_path = processed / f"{stem}.json"
    artifact_path.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    digest = _sha(artifact_path)
    (processed / f"{stem}.sha256").write_text(f"{digest}  {artifact_path.name}\n", encoding="utf-8")
    manifest = {
        **manifest,
        "artifact_sha256": digest,
        "artifact_path": f"data/processed/{artifact_path.name}",
    }
    (manifests / f"{stem}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _estimate_dict(estimate: Any, *, metric: str, unit: str) -> dict[str, Any]:
    return {"metric": metric, "unit": unit, **asdict(estimate)}


def build_meps() -> None:
    result = ingest_meps(MEPS_ZIP, cache_dir=None)
    rows = [dict(row) for row in result.valid]
    retrieved_at = _now()
    domain_rows = [
        row
        for row in rows
        if row["proxy_weight"] and row["dcs_eligible"] == 1 and row["diabetes_reported"] == 1
    ]
    complete = [row["kidney_problem_proxy"] in (1, 2) for row in domain_rows]
    source_population = (
        "MEPS HC-243 2022 Diabetes Care Survey-eligible respondents with self-reported "
        "diabetes; DSKIDN53 is a diabetes-related kidney-problem proxy, not confirmed CKD"
    )
    common = {
        "weights": [row["proxy_weight"] for row in domain_rows],
        "strata": [row["variance_stratum"] for row in domain_rows],
        "psu": [row["variance_psu"] for row in domain_rows],
        "domain": complete,
        "lonely_psu": "certainty",
        "source_population": source_population,
    }
    prevalence = weighted_prevalence(
        [
            int(row["kidney_problem_proxy"] == 1) if is_complete else None
            for row, is_complete in zip(domain_rows, complete, strict=True)
        ],
        **common,
    )
    estimates = [_estimate_dict(prevalence, metric="proxy_positive_prevalence", unit="proportion")]
    for field, unit in (
        ("office_visits", "visits per person-year"),
        ("outpatient_visits", "visits per person-year"),
        ("emergency_visits", "visits per person-year"),
        ("inpatient_stays", "stays per person-year"),
        ("prescription_medicines", "medicines per person-year"),
        ("total_expenditure_usd", "USD per person-year"),
    ):
        estimate = weighted_mean([row[field] for row in domain_rows], **common)
        estimates.append(_estimate_dict(estimate, metric=field, unit=unit))
    artifact = {
        "artifact": "MEPS HC-243 2022 utilization and expenditure landscape",
        "evidence_type": "public_observed",
        "release": "HC-243-2022",
        "retrieved_at": retrieved_at,
        "source": "MEPS / AHRQ",
        "source_url": "https://meps.ahrq.gov/mepsweb/data_files/pufs/h243/h243dat.zip",
        "source_sha256": _sha(MEPS_ZIP),
        "definition": {
            "proxy_variable": "DSKIDN53",
            "proxy_is_not_confirmed_ckd": True,
            "proxy_domain": "DCSELIG=1 and DSDIA53=1; complete DSKIDN53 in {1,2}",
            "weight": "DIABW22F",
            "design": ["VARSTR", "VARPSU"],
            "variance": "Taylor linearization with certainty treatment for lonely PSUs",
        },
        "denominators": {
            "all_person_records": len(rows),
            "design_eligible_person_records": sum(bool(row["person_weight"]) for row in rows),
            "dcs_eligible_records": sum(row["dcs_eligible"] == 1 for row in rows),
            "diabetes_reported_records": len(domain_rows),
            "proxy_complete_records": sum(complete),
            "proxy_positive_records": sum(
                row["kidney_problem_proxy"] == 1 and ok
                for row, ok in zip(domain_rows, complete, strict=True)
            ),
            "proxy_negative_records": sum(
                row["kidney_problem_proxy"] == 2 and ok
                for row, ok in zip(domain_rows, complete, strict=True)
            ),
            "proxy_missing_records": len(domain_rows) - sum(complete),
        },
        "estimates": estimates,
        "limitations": [
            "HC-243 does not provide a confirmed CKD diagnosis variable for this analysis.",
            (
                "The proxy is restricted to DCS-eligible respondents with self-reported "
                "diabetes and uses DIABW22F; it is not a provider-prescribing or claims "
                "population."
            ),
            (
                "Utilization and expenditure estimates are descriptive person-year survey "
                "estimates; they are not causal or commercial forecasts."
            ),
        ],
    }
    manifest = {
        "source": "MEPS / AHRQ",
        "release": "HC-243-2022",
        "retrieved_at": retrieved_at,
        "source_url": artifact["source_url"],
        "source_sha256": artifact["source_sha256"],
        "source_bytes": MEPS_ZIP.stat().st_size,
        "record_count": len(rows),
        "valid_count": len(result.valid),
        "quarantine_count": len(result.quarantine),
        "grain": "source-specific person-year aggregate; no event-person linkage",
    }
    _write("meps_hc243_2022_landscape", artifact, manifest)


DICTIONARY: dict[str, dict[str, str]] = {
    "Empagliflozin": {
        "class": "SGLT2 inhibitor",
        "rationale": (
            "CKD risk-reduction and kidney-care therapy class; inclusion is a descriptive "
            "drug dictionary, not an indication claim."
        ),
    },
    "Dapagliflozin Propanediol": {
        "class": "SGLT2 inhibitor",
        "rationale": (
            "CKD risk-reduction and kidney-care therapy class; inclusion is a descriptive "
            "drug dictionary, not an indication claim."
        ),
    },
    "Finerenone": {
        "class": "nonsteroidal mineralocorticoid receptor antagonist",
        "rationale": (
            "Kidney and cardiovascular risk-reduction therapy class; inclusion is a "
            "descriptive drug dictionary, not an indication claim."
        ),
    },
}


def build_partd() -> None:
    retrieval = json.loads((PARTD_DIR / "retrieval-manifest.json").read_text(encoding="utf-8"))
    aggregate: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in retrieval["generics"]:
        generic = str(item["generic"])
        slug = generic.lower().replace(" ", "-")
        for page in item["pages"]:
            page_path = PARTD_DIR / f"{slug}-{page['offset']}.json"
            if _sha(page_path) != page["sha256"]:
                raise ValueError(f"CMS page checksum mismatch: {page_path}")
            rows = json.loads(page_path.read_text(encoding="utf-8"))
            if len(rows) != page["rows"]:
                raise ValueError(f"CMS page row-count mismatch: {page_path}")
            for row in rows:
                key = (
                    generic,
                    str(row.get("Brnd_Name", "")),
                    str(row.get("Prscrbr_State_Abrvtn", "")),
                )
                target = aggregate.setdefault(
                    key,
                    {
                        "generic_name": generic,
                        "brand_name": key[1],
                        "provider_state": key[2],
                        "provider_ids": set(),
                        "total_claims": 0,
                        "total_30day_fills": 0.0,
                        "total_drug_cost_usd": 0.0,
                    },
                )
                target["provider_ids"].add(str(row.get("Prscrbr_NPI", "")))
                target["total_claims"] += int(float(row.get("Tot_Clms") or 0))
                target["total_30day_fills"] += float(row.get("Tot_30day_Fills") or 0)
                target["total_drug_cost_usd"] += float(row.get("Tot_Drug_Cst") or 0)
    aggregates = []
    for key in sorted(aggregate):
        row = aggregate[key]
        aggregates.append(
            {
                k: (
                    len(row["provider_ids"])
                    if k == "provider_count"
                    else round(row[k], 2)
                    if isinstance(row[k], float)
                    else row[k]
                )
                for k in (
                    "generic_name",
                    "brand_name",
                    "provider_state",
                    "total_claims",
                    "total_30day_fills",
                    "total_drug_cost_usd",
                )
            }
            | {"provider_count": len(row["provider_ids"])}
        )
    retrieved_at = str(retrieval["retrieved_at"])
    artifact = {
        "artifact": "CMS Medicare Part D 2024 selected CKD-therapy landscape",
        "evidence_type": "public_observed",
        "release": "2024",
        "retrieved_at": retrieved_at,
        "source": "CMS Medicare Part D Prescribers by Provider and Drug",
        "source_url": "https://data.cms.gov/provider-summary-by-type-of-service/medicare-part-d-prescribers/medicare-part-d-prescribers-by-provider-and-drug",
        "dataset_uuid": retrieval["dataset_uuid"],
        "dictionary_version": "ckd-therapy-dictionary-v1",
        "dictionary": [
            {"generic_name": generic, **details} for generic, details in sorted(DICTIONARY.items())
        ],
        "pagination": {
            "complete_for_selected_generics": retrieval["pagination_complete"],
            "page_size": retrieval["page_size"],
            "rows_retrieved": sum(item["rows_retrieved"] for item in retrieval["generics"]),
            "generic_pages": [
                {
                    "generic": item["generic"],
                    "pages": len(item["pages"]),
                    "rows_retrieved": item["rows_retrieved"],
                    "offsets": [page["offset"] for page in item["pages"]],
                    "page_checksums": [
                        {
                            "offset": page["offset"],
                            "rows": page["rows"],
                            "bytes": page["bytes"],
                            "sha256": page["sha256"],
                            "url": page["url"],
                        }
                        for page in item["pages"]
                    ],
                }
                for item in retrieval["generics"]
            ],
        },
        "aggregates": aggregates,
        "limitations": {
            "privacy_suppression": (
                "CMS detailed provider-drug data exclude providers with fewer than 11 "
                "total claims; absent rows are not zero and beneficiary fields are not used."
            ),
            "interpretation": (
                "Provider-drug aggregates describe reported Medicare Part D activity for "
                "the selected generic dictionary; they do not establish CKD indication, "
                "adherence, outcomes, or patient journeys."
            ),
        },
    }
    manifest = {
        "source": artifact["source"],
        "release": "2024",
        "retrieved_at": retrieved_at,
        "source_url": artifact["source_url"],
        "dataset_uuid": retrieval["dataset_uuid"],
        "retrieval_manifest_sha256": _sha(PARTD_DIR / "retrieval-manifest.json"),
        "pagination_complete": retrieval["pagination_complete"],
        "rows_retrieved": artifact["pagination"]["rows_retrieved"],
        "grain": (
            "provider-drug-state aggregate; provider identifiers removed from committed output"
        ),
    }
    _write("partd_2024_ckd_therapy_landscape", artifact, manifest)


def build_trials() -> None:
    result = ingest_trials(CTG_JSON, cache_dir=None)
    document = json.loads(CTG_JSON.read_text(encoding="utf-8"))
    metadata = document["snapshot_metadata"]
    valid = [dict(row) for row in result.valid]
    raw_ids = {
        study.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
        for study in document["studies"]
    }
    raw_ids.discard(None)
    missing = sum(row["enrollment"] is None for row in valid)
    artifact = {
        "artifact": "ClinicalTrials.gov CKD registry landscape",
        "evidence_type": "public_observed",
        "release": "api-v2",
        "retrieved_at": metadata["retrieved_at"],
        "source": "ClinicalTrials.gov",
        "endpoint": metadata["endpoint"],
        "query": metadata["query"],
        "counts": {
            "api_total_count": metadata["total_count"],
            "valid_count": len(valid),
            "quarantine_count": len(result.quarantine),
            "unique_nct_ids": len(raw_ids),
            "studies_with_missing_enrollment": missing,
            "studies_with_reported_enrollment": len(valid) - missing,
            "quarantine_reasons": {
                reason: count
                for reason, count in sorted(
                    (reason, sum(reason in q.reasons for q in result.quarantine))
                    for reason in sorted({r for q in result.quarantine for r in q.reasons})
                )
            },
        },
        "status": summarize_trial_status(valid),
        "phase_or_type": summarize_trial_composition(valid),
        "sponsor": _group_sponsor(valid),
        "geography": summarize_trial_geography(valid),
        "change_over_time": summarize_trial_updates(valid),
        "limitations": [
            (
                "Registry status, sponsor, geography, and enrollment are submitted study "
                "metadata, not patient outcomes or treatment effectiveness."
            ),
            "Missing enrollment is preserved as null in grouped rows; it is never recoded to zero.",
        ],
    }
    manifest = {
        "source": artifact["source"],
        "release": "api-v2",
        "retrieved_at": metadata["retrieved_at"],
        "endpoint": metadata["endpoint"],
        "query": metadata["query"],
        "page_count": metadata["page_count"],
        "page_size": metadata["page_size"],
        "api_total_count": metadata["total_count"],
        "valid_count": len(valid),
        "quarantine_count": len(result.quarantine),
        "raw_snapshot_sha256": _sha(CTG_JSON),
        "raw_snapshot_bytes": CTG_JSON.stat().st_size,
        "pagination_complete": metadata["pagination_complete"],
        "grain": "registered study aggregate; no study IDs committed",
    }
    _write("clinicaltrials_ckd_landscape", artifact, manifest)


def _group_sponsor(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[str(row["sponsor"])] += 1
    total = len(rows)
    return [
        {
            "sponsor": sponsor,
            "study_count": count,
            "share_of_registered_studies": count / total if total else 0.0,
            "source": "ClinicalTrials.gov",
            "evidence_type": "public_observed",
            "grain": "registered study grouped by lead sponsor",
        }
        for sponsor, count in sorted(counts.items())
    ]


if __name__ == "__main__":
    build_meps()
    build_partd()
    build_trials()
