from __future__ import annotations

from typing import Any

from dash import html

from .common import accessible_table, coverage_note, evidence_header, limitation, page_shell


def render(data: dict[str, Any]) -> html.Main:
    utilization = data.get("utilization", {})
    prescribing = data.get("prescribing", {})
    return page_shell(
        "Care and prescribing signals",
        (
            "Two source-specific panels: consolidated MEPS person-year utilization and "
            "CMS Part D provider-drug-state aggregates."
        ),
        [
            limitation(
                (
                    "Provider-state prescribing is not beneficiary geography; suppressed "
                    "values are not zeros."
                ),
                tone="strong",
            ),
            html.Section(
                [
                    html.H2("MEPS utilization"),
                    coverage_note(utilization),
                    evidence_header(utilization.get("evidence", {})),
                    accessible_table(
                        utilization.get("items", []), title="HC-243 person-year estimates", limit=8
                    ),
                ],
                className="section",
            ),
            html.Section(
                [
                    html.H2("Part D prescribing"),
                    coverage_note(prescribing),
                    evidence_header(prescribing.get("evidence", {})),
                    accessible_table(
                        prescribing.get("items", []), title="Provider-state aggregates", limit=12
                    ),
                ],
                className="section",
            ),
        ],
    )
