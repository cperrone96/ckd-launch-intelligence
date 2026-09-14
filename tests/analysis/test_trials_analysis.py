from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from ckd_intelligence.analysis.trials import (
    summarize_trial_composition,
    summarize_trial_geography,
    summarize_trial_status,
    summarize_trial_updates,
)


def _row(evidence_type: str) -> dict[str, object]:
    return {
        "nct_id": "NCT00000001",
        "overall_status": "RECRUITING",
        "study_type": "INTERVENTIONAL",
        "phase": "PHASE2",
        "last_update_date": "2026-01-01",
        "enrollment": None,
        "country": "United States",
        "evidence_type": evidence_type,
    }


@pytest.mark.parametrize(
    "summary",
    [
        summarize_trial_status,
        summarize_trial_composition,
        summarize_trial_geography,
        summarize_trial_updates,
    ],
)
def test_analysis_preserves_fixture_only_provenance(
    summary: Callable[[list[dict[str, object]]], list[dict[str, Any]]],
) -> None:
    rows = summary([_row("fixture_only")])
    assert rows
    assert {row["evidence_type"] for row in rows} == {"fixture_only"}


def test_analysis_rejects_mixed_evidence_types() -> None:
    rows = [_row("public_observed"), {**_row("fixture_only"), "nct_id": "NCT00000002"}]
    with pytest.raises(ValueError, match="one explicit evidence_type"):
        summarize_trial_status(rows)
