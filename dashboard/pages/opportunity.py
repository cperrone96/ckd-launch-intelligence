from __future__ import annotations

from typing import Any

from dash import html

from .common import accessible_table, evidence_header, limitation, page_shell


def render(data: dict[str, Any]) -> html.Main:
    opportunity = data.get("opportunity", {})
    evidence = opportunity.get("evidence", [])
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
                    html.Div(
                        [
                            accessible_table(rows, title=title.replace("_", " ").title(), limit=10)
                            for title, rows in opportunity.get("source_panels", {}).items()
                        ]
                    ),
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
