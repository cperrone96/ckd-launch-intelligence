from __future__ import annotations

from typing import Any

from dash import html

from .common import (
    accessible_table,
    coverage_note,
    empty_state,
    evidence_header,
    has_nonempty_list,
    has_structured_evidence,
    limitation,
    page_shell,
)


def render(data: dict[str, Any]) -> html.Main:
    utilization = data.get("utilization", {})
    prescribing = data.get("prescribing", {})
    has_utilization = isinstance(utilization, dict) and has_structured_evidence(
        utilization.get("evidence")
    )
    has_prescribing = isinstance(prescribing, dict) and has_structured_evidence(
        prescribing.get("evidence")
    )
    has_any_rows = has_nonempty_list(utilization, "items") or has_nonempty_list(
        prescribing, "items"
    )
    if (not has_utilization and not has_prescribing) or not has_any_rows:
        return page_shell(
            "Care and prescribing signals",
            (
                "Two source-specific panels: consolidated MEPS person-year utilization and "
                "CMS Part D provider-drug-state aggregates."
            ),
            [
                limitation(
                    "Provider-state prescribing is not beneficiary geography; suppressed values "
                    "are not zeros.",
                    tone="strong",
                ),
                empty_state(
                    "Care and prescribing evidence is unavailable in this API response; no source "
                    "metrics or provenance are displayed."
                ),
            ],
        )

    def source_section(
        title: str, payload: dict[str, Any], table_title: str, limit: int
    ) -> html.Section:
        if not has_structured_evidence(payload.get("evidence")):
            return html.Section(
                [
                    html.H2(title),
                    empty_state(f"{title} evidence is unavailable in this API response."),
                ],
                className="section",
            )
        return html.Section(
            [
                html.H2(title),
                coverage_note(payload),
                evidence_header(payload["evidence"]),
                accessible_table(payload.get("items", []), title=table_title, limit=limit),
            ],
            className="section",
        )

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
            source_section("MEPS utilization", utilization, "HC-243 person-year estimates", 8),
            source_section("Part D prescribing", prescribing, "Provider-state aggregates", 12),
        ],
    )
