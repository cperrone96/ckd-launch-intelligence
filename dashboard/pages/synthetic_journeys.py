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


def _summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "index_date",
        "target_date",
        "persistence_date",
        "duration_days",
        "event_observed",
        "censoring_reason",
    )
    return [{field: row.get(field) for field in fields} for row in rows]


def _survival_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = ("time", "at_risk", "events", "censored", "survival", "ci_low", "ci_high")
    return [{field: row.get(field) for field in fields} for row in rows]


def render(data: dict[str, Any]) -> html.Main:
    journey = data.get("journey", {})
    summaries = _summary_rows(journey.get("summaries", []))
    survival = _survival_rows(journey.get("survival", []))
    evidence = journey.get("evidence", {})
    if (
        not has_structured_evidence(evidence)
        or not has_nonempty_list(journey, "summaries")
        or not has_nonempty_list(journey, "survival")
    ):
        return page_shell(
            "Synthetic claims journeys",
            "CMS synthetic data used to demonstrate claims-engineering and time-to-event methods.",
            [
                limitation(
                    "CMS synthetic data; not representative of Medicare beneficiaries and not "
                    "evidence about real beneficiaries.",
                    tone="strong",
                ),
                empty_state(
                    "Synthetic-journey evidence is unavailable in this API response; no journey "
                    "metrics or provenance are displayed."
                ),
            ],
        )
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
                evidence,
                extra="Fixture-only journey rules; no cross-source join.",
            ),
            html.Section(
                [
                    html.H2("Journey summaries"),
                    accessible_table(summaries, title="Synthetic journey summary", limit=10),
                ],
                className="section",
            ),
            html.Section(
                [
                    html.H2("Survival method output"),
                    accessible_table(survival, title="Synthetic time-to-event table", limit=12),
                ],
                className="section",
            ),
            html.Details(
                [
                    html.Summary("Rules used"),
                    html.P(str(journey.get("rules", {}).get("rule_text", ""))),
                ],
                className="method-details",
            ),
        ],
    )
