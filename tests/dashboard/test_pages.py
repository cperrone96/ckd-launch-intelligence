from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from dashboard.api_client import DashboardAPI
from dashboard.app import _page, create_dashboard
from dashboard.pages import (
    care_and_prescribing,
    opportunity,
    patient_finding,
    patient_need,
    summary,
    synthetic_journeys,
    trials,
)


@pytest.fixture()
def dash_client() -> FlaskClient:
    app = create_dashboard()
    app.server.config.update(TESTING=True)
    return app.server.test_client()


def rendered_json(path: str) -> str:
    rendered = _page(path, DashboardAPI())
    return component_json(rendered)


def component_json(component: object) -> str:
    return json.dumps(component.to_plotly_json(), default=str)  # type: ignore[attr-defined]


def _evidence() -> dict[str, object]:
    return {
        "evidence_type": "public_observed",
        "source_population": "Public aggregate test population",
        "grain": "Source-specific aggregate",
        "source_date_or_window": "2024",
        "join_policy": "No cross-source join",
        "provenance": {
            "artifact": "data/processed/test.json",
            "sha256": "a" * 64,
            "manifest": "data/manifests/test.json",
        },
    }


def test_summary_route_has_decision_first_content(dash_client: FlaskClient) -> None:
    response = dash_client.get("/")
    assert response.status_code == 200
    assert b"evidence-boot" not in response.data
    body = rendered_json("/")
    assert "What can this evidence support?" in body
    assert "13.9%" in body
    assert "5,016" in body
    assert "12.5" in body and "15.3" in body
    assert "/patient-need" in body and "/patient-finding" in body


def test_synthetic_page_never_implies_real_claims(dash_client: FlaskClient) -> None:
    page = dash_client.get("/synthetic-journeys")
    assert page.status_code == 200
    body = rendered_json("/synthetic-journeys")
    assert "CMS synthetic data" in body
    assert "not representative of Medicare beneficiaries" in body
    assert "beneficiary_id" not in body


def test_patient_finding_page_has_non_diagnostic_label(dash_client: FlaskClient) -> None:
    page = dash_client.get("/patient-finding")
    assert page.status_code == 200
    body = rendered_json("/patient-finding")
    assert "not a clinical diagnostic tool" in body
    assert "Not stated" not in body
    assert "Logistic Regression" in body
    assert "logistic_regression" not in body
    assert "subgroup-metric-grid" in body
    assert "Subgroup note" in body
    assert body.index("Cohort n") < body.index("Subgroup note")
    assert "5.2%" in body
    assert "None" not in body


@pytest.mark.parametrize(
    ("renderer", "message"),
    [
        (summary.render, "Summary evidence is unavailable"),
        (patient_need.render, "Patient-need evidence is unavailable"),
        (patient_finding.render, "Patient-finding evidence is unavailable"),
        (care_and_prescribing.render, "Care and prescribing evidence is unavailable"),
        (trials.render, "Trial evidence is unavailable"),
        (opportunity.render, "Opportunity evidence is unavailable"),
        (synthetic_journeys.render, "Synthetic-journey evidence is unavailable"),
    ],
)
def test_empty_api_stubs_render_page_level_empty_states(renderer: object, message: str) -> None:
    body = component_json(renderer({}))  # type: ignore[operator]
    assert message in body
    assert "evidence-panel" not in body
    assert "Not stated" not in body
    assert "unknown" not in body.casefold()


@pytest.mark.parametrize(
    ("renderer", "payload", "message"),
    [
        (
            summary.render,
            {"sources": [], "estimates": {"items": [], "evidence": _evidence()}},
            "Summary evidence is unavailable",
        ),
        (
            patient_need.render,
            {
                "cohort": {"items": []},
                "estimates": {"items": []},
                "evidence": _evidence(),
            },
            "Patient-need evidence is unavailable",
        ),
        (
            patient_finding.render,
            {"performance": {"evidence": _evidence(), "comparison": {"models": {}}}},
            "Patient-finding evidence is unavailable",
        ),
        (
            care_and_prescribing.render,
            {
                "utilization": {"evidence": _evidence(), "items": []},
                "prescribing": {"evidence": _evidence(), "items": []},
            },
            "Care and prescribing evidence is unavailable",
        ),
        (
            trials.render,
            {"sections": {"status": {"evidence": _evidence(), "items": []}}},
            "Trial evidence is unavailable",
        ),
        (
            opportunity.render,
            {
                "opportunity": {
                    "evidence": [_evidence()],
                    "source_panels": {"national": {"items": []}},
                }
            },
            "Opportunity evidence is unavailable",
        ),
        (
            synthetic_journeys.render,
            {"journey": {"evidence": _evidence(), "summaries": [], "survival": []}},
            "Synthetic-journey evidence is unavailable",
        ),
    ],
)
def test_valid_empty_payloads_render_page_level_empty_states(
    renderer: object, payload: dict[str, object], message: str
) -> None:
    body = component_json(renderer(payload))  # type: ignore[operator]
    assert message in body
    assert "evidence-panel" not in body
    assert "Not stated" not in body


def test_mobile_disclosures_and_summary_actions_have_touch_targets() -> None:
    styles = (
        Path(__file__).resolve().parents[2] / "dashboard" / "assets" / "styles.css"
    ).read_text()
    assert ".method-details summary, .table-alternative summary" in styles
    assert ".summary-links a" in styles
    assert styles.count("min-height: 44px") >= 3
    assert ".subgroup-metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }" in styles


@pytest.mark.parametrize(
    "path,required",
    [
        ("/patient-need", ["Source population", "Denominator", "Uncertainty"]),
        ("/care-and-prescribing", ["MEPS", "Part D", "Provider-state"]),
        ("/trials", ["ClinicalTrials.gov", "Registered study"]),
        ("/opportunity", ["Scenario-only", "No composite"]),
    ],
)
def test_each_view_carries_evidence_boundary(
    dash_client: FlaskClient, path: str, required: list[str]
) -> None:
    body = rendered_json(path)
    assert all(term.casefold() in body.casefold() for term in required)


def test_trials_uses_clinicaltrials_evidence_and_discloses_windows() -> None:
    body = rendered_json("/trials")
    assert "ClinicalTrials.gov" in body
    assert "Showing 100 of 110 rows" in body
    assert "partial page window" in body


def test_care_discloses_partd_partial_window() -> None:
    body = rendered_json("/care-and-prescribing")
    assert "Showing 100 of 220 rows" in body
    assert "partial page window" in body


def test_api_error_and_empty_states_are_explicit() -> None:
    from dashboard.api_client import DashboardAPI, DashboardAPIError
    from dashboard.pages.common import empty_state, error_state, loading_state

    assert "Unable to load" in component_json(error_state("Unable to load evidence."))
    assert "No compatible" in component_json(empty_state("No compatible results."))
    assert "Loading" in component_json(loading_state())
    with pytest.raises(DashboardAPIError):
        DashboardAPI(base_url="http://127.0.0.1:1").get("/does-not-exist")


def test_every_dashboard_callback_renders_against_current_api_contract() -> None:
    api = DashboardAPI()
    for path in (
        "/",
        "/patient-need",
        "/patient-finding",
        "/care-and-prescribing",
        "/trials",
        "/opportunity",
        "/synthetic-journeys",
    ):
        rendered = _page(path, api)
        assert rendered is not None


def test_opportunity_callback_uses_complete_typed_panels() -> None:
    rendered = _page("/opportunity", DashboardAPI())
    body = component_json(rendered)
    assert "220 source-specific rows" in body
    assert "110 source-specific rows" in body
    assert body.count("complete panel") >= 2
