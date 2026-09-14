from __future__ import annotations

from typing import Any

from dash import html

from .common import accessible_table, evidence_header, limitation, metric, page_shell


def render(data: dict[str, Any]) -> html.Main:
    sources = data.get("sources", [])
    need = data.get("need", {})
    performance = data.get("performance", {}).get("comparison", {})
    evidence = data.get("evidence", {})
    return page_shell(
        "What can this evidence support?",
        (
            "A public-data decision surface for CKD launch intelligence. Start with the "
            "supported readout, then open the method behind each finding."
        ),
        [
            html.Div(
                [
                    metric(
                        "Population signal", "13.9%", "NHANES primary eGFR or albuminuria estimate"
                    ),
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
                                    html.P(
                                        f"{performance.get('selected_model', 'Reviewed')} model "
                                        "comparison and threshold capacity."
                                    ),
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
            html.P(
                f"Waterfall stages available · {len(need.get('items', []))}",
                className="source-count",
            ),
        ],
    )
