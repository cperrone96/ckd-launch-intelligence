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


def test_summary_route_has_decision_first_content(dash_client: FlaskClient) -> None:
    response = dash_client.get("/")
    assert response.status_code == 200
    assert b"What can this evidence support?" in response.data
    assert b"Source boundary" in response.data


def test_synthetic_page_never_implies_real_claims(dash_client: FlaskClient) -> None:
    page = dash_client.get("/synthetic-journeys")
    assert page.status_code == 200
    assert b"CMS synthetic data" in page.data
    assert b"not representative of Medicare beneficiaries" in page.data
    assert b"beneficiary_id" not in page.data


def test_patient_finding_page_has_non_diagnostic_label(dash_client: FlaskClient) -> None:
    page = dash_client.get("/patient-finding")
    assert page.status_code == 200
    assert b"not a clinical diagnostic tool" in page.data


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
    body = dash_client.get(path).data.decode("utf-8")
    assert all(term.casefold() in body.casefold() for term in required)


def test_api_error_and_empty_states_are_explicit() -> None:
    from dashboard.api_client import DashboardAPI, DashboardAPIError
    from dashboard.pages.common import empty_state, error_state, loading_state

    assert "Unable to load" in json.dumps(error_state("Unable to load evidence."))
    assert "No compatible" in json.dumps(empty_state("No compatible results."))
    assert "Loading" in json.dumps(loading_state())
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
    body = json.dumps(rendered.to_plotly_json(), default=str)
    assert "220 source-specific rows" in body
    assert "110 source-specific rows" in body
    assert body.count("complete panel") >= 2
