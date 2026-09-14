from __future__ import annotations

from typing import Any

from dash import Dash, Input, Output, dcc, html

from .api_client import DashboardAPI, DashboardAPIError
from .pages import (
    care_and_prescribing,
    opportunity,
    patient_finding,
    patient_need,
    summary,
    synthetic_journeys,
    trials,
)
from .pages.common import page_shell

NAV = (
    ("/", "Summary"),
    ("/patient-need", "Patient need"),
    ("/patient-finding", "Patient finding"),
    ("/care-and-prescribing", "Care & prescribing"),
    ("/trials", "Trials"),
    ("/opportunity", "Opportunity"),
    ("/synthetic-journeys", "Synthetic journeys"),
)


def nav() -> Any:
    return html.Nav(
        [
            html.Div(
                [
                    html.Span("CKD", className="brand-mark"),
                    html.Span("Launch intelligence", className="brand-name"),
                ],
                className="brand",
            ),
            html.Div(
                [dcc.Link(label, href=href, className="nav-link") for href, label in NAV],
                className="nav-links",
            ),
        ],
        className="side-nav",
        **{"aria-label": "Dashboard sections"},  # type: ignore[arg-type]
    )


def _load_data(api: DashboardAPI, pathname: str) -> dict[str, Any]:
    if pathname == "/":
        estimates = api.get("/api/v1/population-estimates", {"page_size": 100})
        return {
            "sources": api.get("/api/v1/sources").get("sources", []),
            "estimates": estimates,
            "performance": api.get("/api/v1/patient-finding/performance"),
            "evidence": estimates.get("evidence", {}),
        }
    if pathname == "/patient-need":
        estimates = api.get("/api/v1/population-estimates", {"page_size": 100})
        return {
            "cohort": api.get("/api/v1/cohorts", {"page_size": 100}),
            "estimates": estimates,
            "evidence": estimates.get("evidence", {}),
        }
    if pathname == "/patient-finding":
        return {"performance": api.get("/api/v1/patient-finding/performance")}
    if pathname == "/care-and-prescribing":
        return {
            "utilization": api.get("/api/v1/utilization", {"page_size": 100}),
            "prescribing": api.get("/api/v1/prescribing", {"page_size": 100}),
        }
    if pathname == "/trials":
        return {
            "sections": {
                dimension: api.get("/api/v1/trials", {"dimension": dimension, "page_size": 100})
                for dimension in ("status", "phase_or_type", "geography")
            }
        }
    if pathname == "/opportunity":
        return {"opportunity": api.get("/api/v1/geography/opportunity")}
    if pathname == "/synthetic-journeys":
        return {"journey": api.get("/api/v1/journeys/synthetic")}
    return {}


def _page(pathname: str, api: DashboardAPI) -> Any:
    try:
        data = _load_data(api, pathname)
        if pathname == "/patient-need":
            return patient_need.render(data)
        if pathname == "/patient-finding":
            return patient_finding.render(data)
        if pathname == "/care-and-prescribing":
            return care_and_prescribing.render(data)
        if pathname == "/trials":
            return trials.render(data)
        if pathname == "/opportunity":
            return opportunity.render(data)
        if pathname == "/synthetic-journeys":
            return synthetic_journeys.render(data)
        return summary.render(data)
    except DashboardAPIError as error:
        return page_shell(
            "Evidence unavailable",
            "The dashboard could not load the verified API response.",
            [html.Div(html.P(str(error)), className="boundary boundary-error")],
        )


def create_dashboard(*, api: DashboardAPI | None = None) -> Dash:
    client = api or DashboardAPI()
    app = Dash(__name__, title="CKD Launch Intelligence", update_title="Loading evidence…")
    app.index_string = (
        "<!DOCTYPE html><html lang=\"en\"><head>{%metas%}<title>{%title%}</title>"
        "{%favicon%}{%css%}</head><body>{%app_entry%}<footer>{%config%}{%scripts%}"
        "{%renderer%}</footer></body></html>"
    )
    app.layout = html.Div(
        [
            dcc.Location(id="url"),
            nav(),
            html.Div(
                dcc.Loading(html.Div(id="page-content"), type="dot"), className="content-shell"
            ),
        ],
        className="app-shell",
    )

    @app.callback(Output("page-content", "children"), Input("url", "pathname"))
    def update_page(pathname: str | None) -> Any:
        return _page(pathname or "/", client)

    return app


app = create_dashboard()


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=8050)
