"""Source-specific ClinicalTrials.gov landscape summaries.

The functions in this module accept normalized records emitted by
``ingest_trials``.  They intentionally do not merge trial records with MEPS,
Part D, NHANES, or synthetic claims.  A ClinicalTrials.gov row represents a
registered study, not an enrolled patient or an observed treatment outcome.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any


def _text(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"trial record requires non-empty text field: {field}")
    return value.strip()


def _enrollment(row: Mapping[str, Any]) -> int | None:
    value = row.get("enrollment")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("trial enrollment must be a non-negative integer or null")
    return int(value)


def _rows(studies: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    rows = list(studies)
    seen: set[str] = set()
    for row in rows:
        nct_id = _text(row, "nct_id")
        if nct_id in seen:
            raise ValueError(f"duplicate trial record: {nct_id}")
        seen.add(nct_id)
        _text(row, "overall_status")
        _text(row, "study_type")
        _text(row, "phase")
        update = _text(row, "last_update_date")
        try:
            date.fromisoformat(update)
        except ValueError as exc:
            raise ValueError(f"invalid trial update date: {update}") from exc
        _enrollment(row)
    return rows


def _evidence_type(rows: list[Mapping[str, Any]]) -> str:
    """Require source provenance to survive every derived summary."""

    values = {row.get("evidence_type") for row in rows}
    if values - {"public_observed", "fixture_only"} or len(values) != 1:
        raise ValueError("trial rows require one explicit evidence_type")
    value = values.pop()
    assert isinstance(value, str)
    return value


def _aggregate(
    rows: list[Mapping[str, Any]], key_field: str
) -> list[dict[str, object]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_text(row, key_field)].append(row)
    total = len(rows)
    evidence_type = _evidence_type(rows)
    result: list[dict[str, object]] = []
    for key in sorted(grouped):
        group = grouped[key]
        enrollments = [_enrollment(row) for row in group]
        observed_enrollment = [value for value in enrollments if value is not None]
        result.append(
            {
                key_field: key,
                "study_count": len(group),
                "study_share": len(group) / total if total else 0.0,
                "total_reported_enrollment": (
                    sum(observed_enrollment) if observed_enrollment else None
                ),
                "studies_with_reported_enrollment": len(observed_enrollment),
                "source": "ClinicalTrials.gov",
                "evidence_type": evidence_type,
                "grain": "registered clinical study grouped by " + key_field,
            }
        )
    return result


def summarize_trial_status(
    studies: Iterable[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Return a deterministic status composition with reconciled study counts."""

    return _aggregate(_rows(studies), "overall_status")


def summarize_trial_composition(
    studies: Iterable[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Summarize registered studies by type and phase without patient linkage."""

    rows = _rows(studies)
    result: list[dict[str, object]] = []
    for key_field in ("study_type", "phase"):
        result.extend(_aggregate(rows, key_field))
    return result


def summarize_trial_geography(
    studies: Iterable[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Count study-country mentions; multi-country studies contribute once/country."""

    rows = _rows(studies)
    evidence_type = _evidence_type(rows)
    grouped: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        nct_id = _text(row, "nct_id")
        countries = _text(row, "country").split(" | ")
        for country in countries:
            if country.strip():
                grouped[country.strip()].add(nct_id)
    total = len(rows)
    return [
        {
            "country": country,
            "study_count": len(nct_ids),
            "share_of_registered_studies": len(nct_ids) / total if total else 0.0,
            "source": "ClinicalTrials.gov",
            "evidence_type": evidence_type,
            "grain": "registered study-country mention",
        }
        for country, nct_ids in sorted(grouped.items())
    ]


def summarize_trial_updates(
    studies: Iterable[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Summarize registry activity by update year, not enrollment or outcomes."""

    rows = _rows(studies)
    evidence_type = _evidence_type(rows)
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[date.fromisoformat(_text(row, "last_update_date")).year].append(row)
    return [
        {
            "update_year": year,
            "study_count": len(group),
            "source": "ClinicalTrials.gov",
            "evidence_type": evidence_type,
            "grain": "registered study grouped by last update year",
        }
        for year, group in sorted(grouped.items())
    ]
