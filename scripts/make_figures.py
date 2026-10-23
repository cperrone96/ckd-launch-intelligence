"""Render the README headline figure from the committed, checksummed artifacts.

Usage::

    python scripts/make_figures.py

Writes ``docs/figures/key_results.png``. Every plotted value is read from
``data/processed``; nothing is recomputed here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/figures/key_results.png"

INK = "#0b0b0b"
MUTED = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
GRAY = "#8a8984"


def _load(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (ROOT / "data/processed" / name).read_text(encoding="utf-8")
    )
    return payload


def _style(axis: plt.Axes, title: str) -> None:
    axis.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold", pad=10)
    for side in ("top", "right"):
        axis.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axis.spines[side].set_color(GRID)
    axis.tick_params(colors=MUTED, labelsize=9)
    axis.grid(axis="x", color=GRID, linewidth=0.8)
    axis.set_axisbelow(True)


def _discrimination(axis: plt.Axes, model: dict[str, Any]) -> None:
    rows = [
        ("prevalence_no_skill", "No-skill reference", GRAY),
        ("logistic_demographics_only", "Logistic, demographics only", ORANGE),
        ("logistic_regression", "Logistic, 8 pre-lab predictors", BLUE),
        ("random_forest", "Random forest, 8 predictors", AQUA),
    ]
    for position, (key, _label, color) in enumerate(rows):
        metrics = model["models"][key]
        interval = metrics["roc_auc_interval"]
        point = metrics["roc_auc"]
        axis.plot(
            [interval["low"], interval["high"]], [position, position], color=color, linewidth=2
        )
        axis.plot(point, position, "o", color=color, markersize=8, markeredgecolor="white")
        axis.text(point, position + 0.22, f"{point:.3f}", ha="center", fontsize=9, color=INK)
    axis.set_yticks(range(len(rows)), [label for _, label, _ in rows])
    axis.tick_params(axis="y", length=0)
    axis.set_xlim(0.47, 0.82)
    axis.set_ylim(-0.6, len(rows) - 0.3)
    axis.set_xlabel("ROC-AUC, pooled grouped 5-fold CV (95% cluster-bootstrap CI)", color=MUTED)
    _style(axis, "A. Ranking the CKD lab indicator before labs")


def _calibration(axis: plt.Axes, model: dict[str, Any]) -> None:
    bins = model["models"]["logistic_regression"]["calibration_bins"]
    predicted = [item["mean_probability"] for item in bins]
    observed = [item["observed_rate"] for item in bins]
    axis.plot([0, 0.5], [0, 0.5], color=GRAY, linewidth=1, linestyle="--")
    axis.plot(predicted, observed, color=BLUE, linewidth=2, marker="o", markersize=7)
    axis.text(0.30, 0.25, "perfect calibration", rotation=40, color=MUTED, fontsize=8)
    axis.set_xlim(0, 0.5)
    axis.set_ylim(0, 0.5)
    axis.set_xlabel("Mean predicted probability (quintile)", color=MUTED)
    axis.set_ylabel("Observed indicator rate", color=MUTED)
    axis.grid(axis="y", color=GRID, linewidth=0.8)
    _style(axis, "B. Logistic model calibration")


def _spending(axis: plt.Axes, meps: dict[str, Any]) -> None:
    estimates = {row["metric"]: row for row in meps["estimates"]}
    rows = [
        ("total_expenditure_usd__proxy_negative", "Diabetes, no kidney problems", GRAY),
        ("total_expenditure_usd__proxy_positive", "Diabetes, self-reported kidney problems", BLUE),
    ]
    for position, (key, label, color) in enumerate(rows):
        row = estimates[key]
        axis.barh(position, row["point"] / 1000, height=0.5, color=color)
        axis.plot(
            [row["ci_low"] / 1000, row["ci_high"] / 1000],
            [position, position],
            color=INK,
            linewidth=1.2,
        )
        axis.text(
            row["ci_high"] / 1000 + 0.6,
            position,
            f"${row['point']:,.0f}",
            va="center",
            fontsize=9,
            color=INK,
        )
        axis.text(0.4, position + 0.38, label, fontsize=9, color=MUTED)
    difference = estimates["total_expenditure_usd__proxy_positive_minus_negative"]
    axis.set_yticks([])
    axis.set_ylim(-0.5, 1.8)
    axis.set_xlim(0, 38)
    axis.set_xlabel("Total spending per person-year, USD thousands (95% CI)", color=MUTED)
    axis.text(
        0.4,
        1.62,
        f"Difference ${difference['point']:,.0f} "
        f"(95% CI ${difference['ci_low']:,.0f}-${difference['ci_high']:,.0f})",
        fontsize=9,
        color=INK,
    )
    _style(axis, "C. MEPS 2022 spending, adults with diabetes")


def main() -> None:
    model = _load("patient_finding_model_comparison.json")
    meps = _load("meps_hc243_2022_landscape.json")
    figure, axes = plt.subplots(
        1, 3, figsize=(15, 4.4), gridspec_kw={"width_ratios": [1.25, 0.85, 1.1]}
    )
    _discrimination(axes[0], model)
    _calibration(axes[1], model)
    _spending(axes[2], meps)
    figure.tight_layout(w_pad=3)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        OUTPUT,
        dpi=150,
        facecolor="white",
        bbox_inches="tight",
        pad_inches=0.2,
        metadata={"Software": None},
    )
    print(f"wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
