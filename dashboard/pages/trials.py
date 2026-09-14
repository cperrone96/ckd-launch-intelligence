from __future__ import annotations

from typing import Any

from dash import html

from .common import (
    accessible_table,
    chart_with_table,
    coverage_note,
    empty_state,
    evidence_header,
    has_nonempty_list,
    has_structured_evidence,
    limitation,
    page_shell,
)


def render(data: dict[str, Any]) -> html.Main:
    sections = data.get("sections", {})
    status_payload = sections.get("status", {}) if isinstance(sections, dict) else {}
    evidence = status_payload.get("evidence", {}) if isinstance(status_payload, dict) else {}
    status_rows = status_payload.get("items", []) if isinstance(status_payload, dict) else []
    has_any_rows = isinstance(sections, dict) and any(
        has_nonempty_list(payload, "items") for payload in sections.values()
    )
    if not has_structured_evidence(evidence) or not has_any_rows:
        return page_shell(
            "Registered trial landscape",
            (
                "ClinicalTrials.gov registry activity is a signal of registered studies, not "
                "treatment outcomes or enrollment evidence."
            ),
            [
                limitation(
                    "Study-country mentions are not patient geography; multi-country studies "
                    "contribute to each declared country.",
                    tone="strong",
                ),
                empty_state(
                    "Trial evidence is unavailable in this API response; no registered-study "
                    "metrics or provenance are displayed."
                ),
            ],
        )
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
    status_content = (
        chart_with_table(status_figure, status_rows, "Registered status")
        if status_rows
        else empty_state("No ClinicalTrials.gov status aggregates are available.")
    )
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
            status_content,
            html.Div(
                [
                    html.Section(
                        [
                            html.H2(title.replace("_", " ").title()),
                            coverage_note(payload),
                            accessible_table(
                                payload.get("items", []),
                                title="Registered study aggregates",
                                limit=10,
                            ),
                        ]
                        if has_structured_evidence(payload.get("evidence"))
                        else [
                            html.H2(title.replace("_", " ").title()),
                            empty_state(
                                f"{title.replace('_', ' ').title()} evidence is unavailable in "
                                "this API response."
                            ),
                        ],
                        className="section",
                    )
                    for title, payload in sections.items()
                ]
            ),
        ],
    )
