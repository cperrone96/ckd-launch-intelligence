from __future__ import annotations

from typing import Any

from dash import dcc, html

from .common import accessible_table, empty_state, evidence_header, limitation, metric, page_shell


def render(data: dict[str, Any]) -> html.Main:
    sources = data.get("sources", [])
    estimates = data.get("estimates", {})
    performance = data.get("performance", {}).get("comparison", {})
    evidence = estimates.get("evidence", data.get("evidence", {}))
    estimate_rows = estimates.get("items", [])
    primary = next(
        (row for row in estimate_rows if row.get("key") == "primary_egfr_or_albuminuria"),
        None,
    )
    if primary:
        signal_cards = [
            metric(
                "Population signal", f"{primary['point'] * 100:.1f}%", "NHANES primary indicator"
            ),
            metric("Complete-case n", f"{primary['denominator']:,}", "Defining labs available"),
            metric(
                "95% confidence interval",
                f"{primary['ci_low'] * 100:.1f}–{primary['ci_high'] * 100:.1f}%",
                "Survey-weighted uncertainty",
            ),
        ]
    else:
        signal_cards = [empty_state("The primary population estimate is unavailable.")]
    selected_model = performance.get("selected_model")
    model_step = (
        html.P(f"{selected_model} model comparison and threshold capacity.")
        if selected_model
        else empty_state("The model comparison is unavailable.")
    )
    return page_shell(
        "What can this evidence support?",
        (
            "A public-data decision surface for CKD launch intelligence. Start with the "
            "supported readout, then open the method behind each finding."
        ),
        [
            html.Div(
                [
                    *signal_cards,
                    metric("Model use", "Educational", "Screening-opportunity demonstration only"),
                    metric("Geography", "Separated", "Provider-state and study-country panels"),
                ],
                className="metric-grid",
            ),
            limitation(
                (
                    "This dashboard does not diagnose, target patients, or combine "
                    "incompatible source geographies."
                ),
                tone="strong",
            ),
            evidence_header(
                evidence,
                extra="All findings are traceable to committed, checksum-verified API artifacts.",
            ),
            html.Section(
                [
                    html.H2("The review path"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Span("01", className="step-number"),
                                    html.H3("Need"),
                                    html.P("Size and uncertainty of the public survey signal."),
                                ],
                                className="review-step",
                            ),
                            html.Div(
                                [
                                    html.Span("02", className="step-number"),
                                    html.H3("Find"),
                                    model_step,
                                ],
                                className="review-step",
                            ),
                            html.Div(
                                [
                                    html.Span("03", className="step-number"),
                                    html.H3("Act carefully"),
                                    html.P(
                                        "Care, prescribing, trials, and scenario boundaries stay "
                                        "source-specific."
                                    ),
                                ],
                                className="review-step",
                            ),
                        ],
                        className="review-steps",
                    ),
                ],
                className="section",
            ),
            accessible_table(sources, title="Verified sources on hand", limit=8),
            html.Div(
                [
                    dcc.Link("Open patient-need evidence →", href="/patient-need"),
                    dcc.Link("Open patient-finding review →", href="/patient-finding"),
                ],
                className="summary-links",
            ),
        ],
    )
