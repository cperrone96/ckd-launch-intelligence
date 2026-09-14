"""Tests for fail-closed, scenario-only opportunity ranking."""

from __future__ import annotations

from typing import Any

import pytest

from ckd_intelligence.analysis.opportunity import rank_opportunities


def _evidence(
    value: float | None,
    *,
    component: str,
    key: str,
    time_period: str = "2024",
    coverage: float = 1.0,
) -> dict[str, object]:
    return {
        "value": value,
        "source_population": f"illustrative {component} aggregate",
        "grain": "scenario aggregate",
        "evidence_type": "public_synthetic",
        "provenance": f"tests/{component}.json",
        "geography_scope": "scenario",
        "time_period": time_period,
        "compatibility_key": key,
        "coverage": coverage,
    }


def sample_inputs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, values in (
        ("Alpha", (0.8, 0.7, 0.6, 0.5)),
        ("Beta", (0.4, 0.5, 0.6, 0.7)),
    ):
        rows.append(
            {
                "key": key,
                "geography": key,
                "time_period": "2024",
                "scenario_only": True,
                "compatibility_key": "demo",
                "components": {
                    component: _evidence(
                        value, component=component, key="demo"
                    )
                    for component, value in zip(
                        ("need", "screening_gap", "prescribing", "trial_activity"),
                        values,
                        strict=True,
                    )
                },
            }
        )
    return rows


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        rank_opportunities(sample_inputs(), {"need": 0.8, "access": 0.8})


def test_result_exposes_components_and_sensitivity() -> None:
    result = rank_opportunities(
        sample_inputs(),
        {"need": 0.25, "screening_gap": 0.25, "prescribing": 0.25, "trial_activity": 0.25},
    )

    assert set(result.components) >= {"need", "screening_gap", "prescribing", "trial_activity"}
    assert result.sensitivity
    assert [row.key for row in result.rows] == ["Alpha", "Beta"]
    assert all(row.scorable for row in result.rows)


def test_composite_requires_explicit_scenario_and_compatibility_metadata() -> None:
    row = sample_inputs()[0]
    del row["scenario_only"]
    with pytest.raises(ValueError, match="scenario_only"):
        rank_opportunities([row])

    row = sample_inputs()[0]
    component = row["components"]["need"]
    assert isinstance(component, dict)
    component["compatibility_key"] = "different-source"
    with pytest.raises(ValueError, match="compatible"):
        rank_opportunities([row])


def test_incompatible_time_period_fails_closed() -> None:
    row = sample_inputs()[0]
    component = row["components"]["trial_activity"]
    assert isinstance(component, dict)
    component["time_period"] = "2023"
    with pytest.raises(ValueError, match="time"):
        rank_opportunities([row])


def test_missing_value_is_not_zero_and_makes_row_unscorable() -> None:
    rows = sample_inputs()
    component = rows[0]["components"]["need"]
    assert isinstance(component, dict)
    component["value"] = None

    result = rank_opportunities(rows)
    first = next(row for row in result.rows if row.key == "Alpha")
    assert first.components["need"] is None
    assert first.normalized["need"] is None
    assert first.scorable is False
    assert first.score is None
    assert first.rank is None


def test_all_missing_component_is_still_a_valid_unscorable_result() -> None:
    rows = sample_inputs()
    for row in rows:
        component = row["components"]["need"]
        assert isinstance(component, dict)
        component["value"] = None

    result = rank_opportunities(rows)
    assert all(row.scorable is False for row in result.rows)
    assert result.normalization["need"]["minimum"] == "null"


def test_low_coverage_is_explicitly_unscorable() -> None:
    rows = sample_inputs()
    component = rows[1]["components"]["screening_gap"]
    assert isinstance(component, dict)
    component["coverage"] = 0.49

    result = rank_opportunities(rows, minimum_coverage=0.5)
    assert result.rows[1].scorable is False
    assert result.rows[1].limitations


def test_scalar_components_require_explicit_scenario_compatibility() -> None:
    row = {
        "key": "Alpha",
        "geography": "Alpha",
        "time_period": "2024",
        "scenario_only": True,
        "compatibility_key": "scenario",
        "need": 1.0,
        "screening_gap": 0.5,
        "prescribing": 0.25,
        "trial_activity": 0.75,
    }
    result = rank_opportunities([row])
    assert result.rows[0].scorable is True
    assert all(value is not None for value in result.rows[0].normalized.values())


def test_rank_ties_are_deterministic_and_documented() -> None:
    rows = sample_inputs()
    for row in rows:
        for component in row["components"].values():
            assert isinstance(component, dict)
            component["value"] = 1.0
    result = rank_opportunities(rows)
    assert [row.key for row in result.rows] == ["Alpha", "Beta"]
    assert [row.rank for row in result.rows] == [1, 2]
    assert result.tie_policy == "score_desc_then_key_asc"
