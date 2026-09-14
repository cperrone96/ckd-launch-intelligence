from __future__ import annotations

from typing import Any

from dash import html

from .common import accessible_table, evidence_header, limitation, page_shell


def render(data: dict[str, Any]) -> html.Main:
    opportunity = data.get("opportunity", {})
    evidence = opportunity.get("evidence", [])
    panel_cards = []
    for title, panel in opportunity.get("source_panels", {}).items():
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
