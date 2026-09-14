from __future__ import annotations

from typing import Any

from dash import html

from .common import accessible_table, evidence_header, limitation, page_shell


def render(data: dict[str, Any]) -> html.Main:
    journey = data.get("journey", {})
    return page_shell(
        "Synthetic claims journeys",
        "CMS synthetic data used to demonstrate claims-engineering and time-to-event methods.",
        [
            limitation(
                (
                    "CMS synthetic data; not representative of Medicare beneficiaries and "
                    "not evidence about real beneficiaries."
                ),
                tone="strong",
            ),
            evidence_header(
                journey.get("evidence", {}),
                extra="Fixture-only journey rules; no cross-source join.",
            ),
            html.Section(
                [
                    html.H2("Journey summaries"),
                    accessible_table(
                        journey.get("summaries", []), title="Synthetic journey summary", limit=10
                    ),
                ],
                className="section",
            ),
            html.Section(
                [
                    html.H2("Survival method output"),
                    accessible_table(
                        journey.get("survival", []), title="Synthetic time-to-event table", limit=12
                    ),
                ],
                className="section",
            ),
            html.Details(
                [
                    html.Summary("Rules used"),
                    html.P(journey.get("rules", {}).get("rule_text", "Rules unavailable.")),
                ],
                className="method-details",
            ),
        ],
    )
