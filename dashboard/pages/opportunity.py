from __future__ import annotations

from typing import Any

from dash import html

from .common import (
    accessible_table,
    empty_state,
    evidence_header,
    has_nonempty_list,
    has_structured_evidence,
    limitation,
    page_shell,
)


def render(data: dict[str, Any]) -> html.Main:
    opportunity = data.get("opportunity", {})
    evidence = opportunity.get("evidence", [])
    source_panels = opportunity.get("source_panels", {})
    has_any_rows = isinstance(source_panels, dict) and any(
        has_nonempty_list(panel, "items") for panel in source_panels.values()
    )
    is_complete = (
        isinstance(evidence, list)
        and bool(evidence)
        and all(has_structured_evidence(item) for item in evidence)
        and isinstance(source_panels, dict)
        and bool(source_panels)
        and has_any_rows
    )
    if not is_complete:
        return page_shell(
            "Opportunity, with the composite withheld",
            (
                "Source panels remain useful when they are not forced into a misleading "
                "geographic ranking."
            ),
            [
                limitation(
                    "Scenario-only. No composite or state leaderboard is published because "
                    "source geographies and time windows are incompatible.",
                    tone="strong",
                ),
                empty_state(
                    "Opportunity evidence is unavailable in this API response; no source panels "
                    "or provenance are displayed."
                ),
            ],
        )
    panel_cards = []
    for title, panel in source_panels.items():
        if not isinstance(panel, dict):
            continue
        rows = panel.get("items", [])
        total = panel.get("total", len(rows) if isinstance(rows, list) else 0)
        complete = panel.get("pagination_complete", False)
        panel_cards.append(
            html.Div(
                [
                    html.P(
                        f"{total} source-specific rows · "
                        f"{'complete panel' if complete else 'partial panel'}",
                        className="table-note",
                    ),
                    accessible_table(
                        rows if isinstance(rows, list) else [],
                        title=title.replace("_", " ").title(),
                        limit=10,
                    ),
                ]
            )
        )
    return page_shell(
        "Opportunity, with the composite withheld",
        (
            "Source panels remain useful when they are not forced into a misleading "
            "geographic ranking."
        ),
        [
            limitation(
                (
                    "Scenario-only. No composite or state leaderboard is published because "
                    "source geographies and time windows are incompatible."
                ),
                tone="strong",
            ),
            html.Div([evidence_header(item) for item in evidence], className="evidence-stack"),
            html.Section(
                [
                    html.H2("Source-specific panels"),
                    html.Div(panel_cards),
                ],
                className="section",
            ),
            html.Section(
                [
                    html.H2("What remains unscored"),
                    html.P(opportunity.get("limitations", "No limitation supplied.")),
                    html.P(
                        "Scenario rankings require explicitly compatible aggregate inputs "
                        "and remain separate from observed evidence."
                    ),
                ],
                className="section section-boundary",
            ),
        ],
    )
