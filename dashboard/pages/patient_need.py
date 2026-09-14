from __future__ import annotations

from typing import Any

from dash import html

from .common import (
    accessible_table,
    chart_with_table,
    empty_state,
    evidence_header,
    has_nonempty_list,
    has_structured_evidence,
    limitation,
    page_shell,
)


def render(data: dict[str, Any]) -> html.Main:
    cohort = data.get("cohort", {})
    estimates = data.get("estimates", {})
    evidence = data.get("evidence", {})
    rows = cohort.get("items", []) if isinstance(cohort, dict) else []
    if (
        not has_structured_evidence(evidence)
        or not has_nonempty_list(cohort, "items")
        or not has_nonempty_list(estimates, "items")
    ):
        return page_shell(
            "Patient need, without overreach",
            (
                "The public survey signal is a population estimate, not a count of identifiable "
                "patients."
            ),
            [
                limitation(
                    "NHANES is a national survey population; it does not support state targeting "
                    "or patient-level linkage.",
                    tone="strong",
                ),
                empty_state(
                    "Patient-need evidence is unavailable in this API response; no estimates or "
                    "provenance are displayed."
                ),
            ],
        )
    figure = {
        "data": [
            {
                "type": "bar",
                "x": [row.get("stage") for row in rows],
                "y": [row.get("people") for row in rows],
                "marker": {"color": "#2e6b5b"},
            }
        ],
        "layout": {
            "title": "Cohort waterfall · people remaining",
            "xaxis": {"title": "Cohort stage"},
            "yaxis": {"title": "People", "rangemode": "tozero"},
            "margin": {"l": 60, "r": 20, "t": 50, "b": 120},
        },
    }
    return page_shell(
        "Patient need, without overreach",
        "The public survey signal is a population estimate, not a count of identifiable patients.",
        [
            evidence_header(
                evidence,
                extra=(
                    "Denominators, confidence intervals, and survey design are shown with "
                    "the estimate."
                ),
            ),
            limitation(
                (
                    "NHANES is a national survey population; it does not support state "
                    "targeting or patient-level linkage."
                ),
                tone="strong",
            ),
            html.Section(
                [
                    html.H2("Cohort waterfall"),
                    chart_with_table(figure, rows, "Cohort waterfall"),
                    accessible_table(rows, title="Included and excluded stages", limit=10),
                ],
                className="section",
            ),
            html.Section(
                [
                    html.H2("Estimates and uncertainty"),
                    accessible_table(
                        estimates.get("items", []),
                        title="Population estimates",
                        limit=6,
                    ),
                ],
                className="section",
            ),
        ],
    )
