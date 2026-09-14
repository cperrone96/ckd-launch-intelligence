from __future__ import annotations

from typing import Any

from dash import html

from .common import accessible_table, evidence_header, limitation, metric, page_shell


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
            "model": name.replace("_", " ").title(),
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


def _subgroup_rows(subgroups: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dimension, groups in subgroups.items():
        if isinstance(groups, list):
            rows.extend(
                {
                    "dimension": dimension,
                    "group": group.get("value"),
                    "n": group.get("n"),
                    "prevalence": group.get("prevalence"),
                    "precision": group.get("precision"),
                    "recall": group.get("recall"),
                    "caveat": group.get("caveat"),
                }
                for group in groups
                if isinstance(group, dict)
            )
    return rows


def render(data: dict[str, Any]) -> html.Main:
    performance = data.get("performance", {})
    comparison = performance.get("comparison", performance)
    evidence = performance.get("evidence", {})
    models = comparison.get("models", {})
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
                        str(comparison.get("selected_model", "Not stated")),
                        "Selected by the committed policy",
                    ),
                    metric(
                        "Threshold",
                        (
                            f"{float(comparison['selected_threshold']):.4f}"
                            if comparison.get("selected_threshold") is not None
                            else "Not stated"
                        ),
                        "Holdout threshold",
                    ),
                    metric(
                        "Holdout n",
                        str(comparison.get("holdout_n", "Not stated")),
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
                    accessible_table(
                        _subgroup_rows(comparison.get("subgroups", {})),
                        title="Subgroup summaries",
                        limit=8,
                    ),
                ],
                className="section",
            ),
        ],
    )
