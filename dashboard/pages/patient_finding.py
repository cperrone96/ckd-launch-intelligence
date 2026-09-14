from __future__ import annotations

from typing import Any

from dash import html

from .common import (
    accessible_table,
    empty_state,
    evidence_header,
    has_structured_evidence,
    limitation,
    metric,
    model_label,
    page_shell,
)


def _model_rows(models: dict[str, Any]) -> list[dict[str, Any]]:
    fields = (
        "roc_auc",
        "pr_auc",
        "brier_score",
        "precision",
        "recall",
        "selected_share",
        "threshold",
    )
    return [
        {
            "model": model_label(name),
            **{
                field: (
                    f"{float(metrics[field]):.4f}"
                    if isinstance(metrics.get(field), (int, float))
                    else metrics.get(field)
                )
                for field in fields
            },
        }
        for name, metrics in models.items()
        if isinstance(metrics, dict)
    ]


def _count_label(value: object) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    return "—"


def _rate_label(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.1%}"
    return "—"


def _subgroup_cards(subgroups: dict[str, Any]) -> list[html.Article]:
    cards: list[html.Article] = []
    for dimension, groups in subgroups.items():
        if isinstance(groups, list):
            for group in groups:
                if not isinstance(group, dict):
                    continue
                caveat = group.get("caveat")
                notes: list[Any] = []
                if isinstance(caveat, str) and caveat.strip():
                    notes.append(
                        html.Details(
                            [html.Summary("Subgroup note"), html.P(caveat)],
                            className="method-details subgroup-note",
                        )
                    )
                cards.append(
                    html.Article(
                        [
                            html.P(
                                str(dimension).replace("_", " ").title(),
                                className="subgroup-label",
                            ),
                            html.H3(str(group.get("value", ""))),
                            html.Div(
                                [
                                    metric(
                                        "Cohort n",
                                        _count_label(group.get("n")),
                                        "Eligible observations",
                                    ),
                                    metric(
                                        "Prevalence",
                                        _rate_label(group.get("prevalence")),
                                        "Observed share",
                                    ),
                                    metric(
                                        "Precision",
                                        _rate_label(group.get("precision")),
                                        "Holdout performance",
                                    ),
                                    metric(
                                        "Recall",
                                        _rate_label(group.get("recall")),
                                        "Holdout performance",
                                    ),
                                ],
                                className="subgroup-metric-grid",
                            ),
                            *notes,
                        ],
                        className="subgroup-card",
                    )
                )
    return cards


def render(data: dict[str, Any]) -> html.Main:
    performance = data.get("performance", {})
    comparison = performance.get("comparison", performance)
    evidence = performance.get("evidence", {})
    models = comparison.get("models", {})
    subgroup_cards = _subgroup_cards(comparison.get("subgroups", {}))
    is_complete = (
        has_structured_evidence(evidence)
        and isinstance(models, dict)
        and bool(models)
        and isinstance(comparison.get("selected_model"), str)
        and comparison.get("selected_threshold") is not None
        and comparison.get("holdout_n") is not None
    )
    if not is_complete:
        return page_shell(
            "Patient finding model review",
            (
                "A leakage-safe, population-analytics comparison with threshold capacity and "
                "subgroup context."
            ),
            [
                limitation(
                    "This score is not a clinical diagnostic tool and must not be used for care "
                    "decisions or patient targeting.",
                    tone="strong",
                ),
                empty_state(
                    "Patient-finding evidence is unavailable in this API response; no model "
                    "metrics or provenance are displayed."
                ),
            ],
        )
    return page_shell(
        "Patient finding model review",
        (
            "A leakage-safe, population-analytics comparison with threshold capacity and "
            "subgroup context."
        ),
        [
            limitation(
                (
                    "This score is not a clinical diagnostic tool and must not be used for "
                    "care decisions or patient targeting."
                ),
                tone="strong",
            ),
            evidence_header(
                evidence,
                extra=(
                    "The model is an educational screening-opportunity demonstration, "
                    "not a clinical instrument."
                ),
            ),
            html.Div(
                [
                    metric(
                        "Selected model",
                        model_label(comparison["selected_model"]),
                        "Selected by the committed policy",
                    ),
                    metric(
                        "Threshold",
                        (
                            f"{float(comparison['selected_threshold']):.4f}"
                            if comparison.get("selected_threshold") is not None
                            else ""
                        ),
                        "Holdout threshold",
                    ),
                    metric(
                        "Holdout n",
                        str(comparison["holdout_n"]),
                        "Reviewed observations",
                    ),
                ],
                className="metric-grid",
            ),
            html.Section(
                [
                    html.H2("Performance and calibration"),
                    accessible_table(
                        _model_rows(models),
                        title="Model comparison",
                        limit=8,
                    ),
                ],
                className="section",
            ),
            html.Section(
                [
                    html.H2("Subgroup and cohort sensitivity"),
                    html.Div(
                        subgroup_cards,
                        className="subgroup-cards",
                    )
                    if subgroup_cards
                    else empty_state(
                        "No subgroup summaries are available in this evidence release."
                    ),
                ],
                className="section",
            ),
        ],
    )
