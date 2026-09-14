from __future__ import annotations

from typing import Any

from dash import html

from .common import accessible_table, evidence_header, limitation, metric, page_shell


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
                        str(comparison.get("selected_threshold", "Not stated")),
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
                        [{"model": key, **value} for key, value in models.items()],
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
                        [
                            {"dimension": key, "groups": str(value)}
                            for key, value in comparison.get("subgroups", {}).items()
                        ],
                        title="Subgroup summaries",
                        limit=8,
                    ),
                ],
                className="section",
            ),
        ],
    )
