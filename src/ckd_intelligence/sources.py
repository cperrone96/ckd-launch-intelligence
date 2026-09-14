"""Typed provenance registry for every supported public-data family."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

EvidenceType = Literal["public_observed", "public_synthetic"]


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Evidence and provenance contract for one source family.

    The checksum authenticates the committed, versioned registry metadata fixture for
    the source. Later ingestion tasks will produce separate manifests for downloaded
    source bytes.
    """

    name: str
    version: str
    retrieved_at: date
    population: str
    grain: str
    evidence_type: EvidenceType
    checksum: str
    limitations: str


_SOURCE_REGISTRY: tuple[SourceRecord, ...] = (
    SourceRecord(
        name="nhanes",
        version="2017-2018",
        retrieved_at=date(2026, 9, 11),
        population="U.S. civilian, noninstitutionalized population represented by NHANES",
        grain="Survey participant examination, questionnaire, and laboratory records",
        evidence_type="public_observed",
        checksum="00d639a526a8f089eb7a81cb9e9196d6105a0fc9aa1adb7f19925eb9803b6e1f",
        limitations=(
            "Cross-sectional indicators are not confirmed diagnoses; survey design "
            "and weights are required."
        ),
    ),
    SourceRecord(
        name="meps",
        version="HC-243-2022",
        retrieved_at=date(2026, 9, 11),
        population="U.S. civilian, noninstitutionalized population represented by MEPS",
        grain="MEPS HC-243 person-year consolidated record with utilization and expenditure fields",
        evidence_type="public_observed",
        checksum="0bcedf41ca415a1b56f94590c10ef957cfa8fe9fe0f657fa10bcf5b451ef62dc",
        limitations=(
            "HC-243 does not contain a confirmed CKD diagnosis; this release uses the "
            "documented DSKIDN53 diabetes-related kidney-problem proxy among DCS-eligible "
            "respondents, with DIABW22F and VARSTR/VARPSU."
        ),
    ),
    SourceRecord(
        name="partd",
        version="2024",
        retrieved_at=date(2026, 9, 11),
        population="Medicare Part D prescriptions represented in CMS aggregate public-use data",
        grain="Aggregated prescriber, drug, and geography records",
        evidence_type="public_observed",
        checksum="f92772168e307682c70f9036d965fd1149d1dd41b7a13f739b77cd6f352b69c0",
        limitations=(
            "Aggregate records do not support beneficiary-level utilization or "
            "patient journeys."
        ),
    ),
    SourceRecord(
        name="clinicaltrials",
        version="api-v2",
        retrieved_at=date(2026, 9, 11),
        population="Studies registered on ClinicalTrials.gov matching documented CKD criteria",
        grain="Registered clinical study",
        evidence_type="public_observed",
        checksum="2230cf6a5a5cc8807bb9b089b37461ead34a5a64944c2272f2862dce5ef14289",
        limitations=(
            "Registry entries reflect submitted records and may be incomplete, "
            "delayed, or changed over time."
        ),
    ),
    SourceRecord(
        name="synpuf",
        version="2008-2010",
        retrieved_at=date(2026, 9, 11),
        population="Synthetic Medicare-like beneficiaries represented by CMS DE-SynPUF",
        grain="Synthetic beneficiary enrollment, claim, and prescription-event records",
        evidence_type="public_synthetic",
        checksum="061696025e275e75aefba2f912e3d5a172b4087bd8fb3f9c9887d053c159466c",
        limitations=(
            "Synthetic data demonstrate engineering methods only and cannot support "
            "Medicare inference."
        ),
    ),
)


def get_source_registry() -> tuple[SourceRecord, ...]:
    """Return the immutable source registry."""

    return _SOURCE_REGISTRY
