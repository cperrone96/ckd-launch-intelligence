from __future__ import annotations

import json

import pytest
from flask.testing import FlaskClient

from dashboard.api_client import DashboardAPI
from dashboard.app import _page, create_dashboard


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
    assert "logistic_regression" in body


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
