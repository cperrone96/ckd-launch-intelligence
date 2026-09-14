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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ckd_intelligence.analysis.trials import (
    summarize_trial_composition,
    summarize_trial_geography,
    summarize_trial_interventions,
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


def _preserved_meps_retrieved_at(source_sha256: str) -> str | None:
    """Preserve acquisition metadata when rebuilding the same HC-243 bytes."""

    manifest_path = ROOT / "data/manifests/meps_hc243_2022_landscape.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    if (
        manifest.get("source") != "MEPS / AHRQ"
        or manifest.get("release") != "HC-243-2022"
        or manifest.get("source_sha256") != source_sha256
    ):
        return None
    retrieved_at = manifest.get("retrieved_at")
    return retrieved_at if isinstance(retrieved_at, str) and retrieved_at.strip() else None


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
    source_sha256 = _sha(MEPS_ZIP)
    retrieved_at = _preserved_meps_retrieved_at(source_sha256) or _now()
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
        **common,  # type: ignore[arg-type]
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
        estimate = weighted_mean([row[field] for row in domain_rows], **common)  # type: ignore[arg-type]
        estimates.append(_estimate_dict(estimate, metric=field, unit=unit))
    artifact = {
        "artifact": "MEPS HC-243 2022 utilization and expenditure landscape",
        "evidence_type": "public_observed",
        "release": "HC-243-2022",
        "retrieved_at": retrieved_at,
        "source": "MEPS / AHRQ",
        "source_url": "https://meps.ahrq.gov/mepsweb/data_files/pufs/h243/h243dat.zip",
        "source_sha256": source_sha256,
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

GENERIC_ALIASES = {name: {name} for name in DICTIONARY}


def _required_text(row: dict[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}:missing_or_suppressed")
    return value.strip()


def _required_nonnegative(row: dict[str, Any], field: str, *, integer: bool = False) -> int | float:
    value = row.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field}:missing_or_suppressed")
    try:
        numeric = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field}:malformed_number") from exc
    if not numeric.is_finite() or numeric < 0:
        raise ValueError(f"{field}:out_of_range")
    if integer and numeric != numeric.to_integral_value():
        raise ValueError(f"{field}:malformed_integer")
    return int(numeric) if integer else float(numeric)


def build_partd() -> None:
    retrieval = json.loads((PARTD_DIR / "retrieval-manifest.json").read_text(encoding="utf-8"))
    aggregate: dict[tuple[str, str, str], dict[str, Any]] = {}
    validation_reasons: dict[str, int] = defaultdict(int)
    valid_row_count = 0
    quarantined_row_count = 0
    for item in retrieval["generics"]:
        generic = str(item["generic"])
        if generic not in GENERIC_ALIASES:
            raise ValueError(f"Generic is not in the versioned dictionary: {generic}")
        slug = generic.lower().replace(" ", "-")
        for page in item["pages"]:
            page_path = PARTD_DIR / f"{slug}-{page['offset']}.json"
            if _sha(page_path) != page["sha256"]:
                raise ValueError(f"CMS page checksum mismatch: {page_path}")
            rows = json.loads(page_path.read_text(encoding="utf-8"))
            if len(rows) != page["rows"]:
                raise ValueError(f"CMS page row-count mismatch: {page_path}")
            for row in rows:
                try:
                    row_generic = _required_text(row, "Gnrc_Name")
                    if row_generic not in GENERIC_ALIASES[generic]:
                        raise ValueError("generic_name:mismatch")
                    brand = _required_text(row, "Brnd_Name")
                    state = _required_text(row, "Prscrbr_State_Abrvtn")
                    provider_npi = _required_text(row, "Prscrbr_NPI")
                    claims = _required_nonnegative(row, "Tot_Clms", integer=True)
                    fills = _required_nonnegative(row, "Tot_30day_Fills")
                    cost = _required_nonnegative(row, "Tot_Drug_Cst")
                except ValueError as exc:
                    quarantined_row_count += 1
                    validation_reasons[str(exc)] += 1
                    continue
                valid_row_count += 1
                key = (generic, brand, state)
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
                target["provider_ids"].add(provider_npi)
                target["total_claims"] += claims
                target["total_30day_fills"] += fills
                target["total_drug_cost_usd"] += cost
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
        "row_validation": {
            "api_rows_retrieved": sum(item["rows_retrieved"] for item in retrieval["generics"]),
            "valid_rows": valid_row_count,
            "quarantined_rows": quarantined_row_count,
            "reasons": dict(sorted(validation_reasons.items())),
            "generic_name_match": (
                "Every retained row's Gnrc_Name must exactly match the "
                "requested dictionary generic."
            ),
        },
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
    page_metadata = metadata.get("pages", [])
    legacy_urls = metadata.get("request_urls", [])
    initial_request_url = (
        page_metadata[0]["request_url"]
        if page_metadata and isinstance(page_metadata[0], dict)
        else legacy_urls[0]
        if legacy_urls
        else metadata["endpoint"]
    )
    dimension_counts = {
        "query_unique_studies": len(valid),
        "status_available": len(valid),
        "study_type_available": sum(row["study_type"] is not None for row in valid),
        "phase_available": sum(row["phase"] is not None for row in valid),
        "intervention_available": sum(row["intervention"] is not None for row in valid),
        "location_available": sum(row["country"] is not None for row in valid),
        "enrollment_reported": len(valid) - missing,
    }
    artifact = {
        "artifact": "ClinicalTrials.gov CKD registry landscape",
        "evidence_type": "public_observed",
        "release": "api-v2",
        "retrieved_at": metadata["retrieved_at"],
        "source": "ClinicalTrials.gov",
        "endpoint": metadata["endpoint"],
        "query": metadata["query"],
        "pagination": {
            "page_count": metadata["page_count"],
            "page_size": metadata["page_size"],
            "total_count": metadata["total_count"],
            "pagination_complete": metadata["pagination_complete"],
            "request_parameter_contract": (
                "query.term, pageSize, countTotal, format, and server-issued pageToken"
            ),
            "initial_request_url": initial_request_url,
            "page_audit": [
                {
                    "page_number": page["page_number"],
                    "rows": page["rows"],
                    "bytes": page["bytes"],
                    "sha256": page["sha256"],
                    "has_page_token": bool(page.get("page_token")),
                }
                for page in page_metadata
            ],
        },
        "counts": {
            "api_total_count": metadata["total_count"],
            "retrieved_row_count": metadata.get("retrieved_row_count", len(document["studies"])),
            "unique_valid_nct_id_count": metadata.get("unique_valid_nct_id_count", len(raw_ids)),
            "valid_count": len(valid),
            "quarantine_count": len(result.quarantine),
            "unique_nct_ids": len(raw_ids),
            "dimension_denominators": dimension_counts,
            "missing_optional_fields": {
                "phase": dimension_counts["query_unique_studies"]
                - dimension_counts["phase_available"],
                "intervention": dimension_counts["query_unique_studies"]
                - dimension_counts["intervention_available"],
                "location": dimension_counts["query_unique_studies"]
                - dimension_counts["location_available"],
                "enrollment": missing,
            },
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
        "intervention": summarize_trial_interventions(valid),
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
        "initial_request_url": initial_request_url,
        "api_total_count": metadata["total_count"],
        "valid_count": len(valid),
        "quarantine_count": len(result.quarantine),
        "raw_snapshot_sha256": _sha(CTG_JSON),
        "raw_snapshot_bytes": CTG_JSON.stat().st_size,
        "pagination_complete": metadata["pagination_complete"],
        "total_counts_observed": metadata.get("total_counts_observed", [metadata["total_count"]]),
        "total_count_stable": metadata.get("total_count_stable", True),
        "total_count_missing_pages": metadata.get("total_count_missing_pages", 0),
        "retrieved_row_count": metadata.get("retrieved_row_count", len(document["studies"])),
        "unique_valid_nct_id_count": metadata.get("unique_valid_nct_id_count", len(raw_ids)),
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
