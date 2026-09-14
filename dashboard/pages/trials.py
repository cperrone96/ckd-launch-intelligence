from __future__ import annotations

from typing import Any

from dash import html

from .common import accessible_table, chart_with_table, evidence_header, limitation, page_shell


def render(data: dict[str, Any]) -> html.Main:
    sections = data.get("sections", {})
    evidence = data.get("evidence", {})
    status_rows = sections.get("status", {}).get("items", [])
    status_figure = {
        "data": [
            {
                "type": "bar",
                "x": [row.get("overall_status") for row in status_rows],
                "y": [row.get("study_count") for row in status_rows],
                "marker": {"color": "#b64b36"},
            }
        ],
        "layout": {
            "title": "Registered studies by status",
            "xaxis": {"title": "Registry status"},
            "yaxis": {"title": "Study count", "rangemode": "tozero"},
            "margin": {"l": 60, "r": 20, "t": 50, "b": 90},
        },
    }
    return page_shell(
        "Registered trial landscape",
        (
            "ClinicalTrials.gov registry activity is a signal of registered studies, not "
            "treatment outcomes or enrollment evidence."
        ),
        [
            limitation(
                (
                    "Study-country mentions are not patient geography; multi-country studies "
                    "contribute to each declared country."
                ),
                tone="strong",
            ),
            evidence_header(evidence),
            chart_with_table(status_figure, status_rows, "Registered status"),
            html.Div(
                [
                    html.Section(
                        [
                            html.H2(title.replace("_", " ").title()),
                            accessible_table(
                                payload.get("items", []),
                                title="Registered study aggregates",
                                limit=10,
                            ),
                        ],
                        className="section",
                    )
                    for title, payload in sections.items()
                ]
            ),
        ],
    )
