from __future__ import annotations

from typing import Any

from dash import dash_table, dcc, html


def evidence_header(evidence: dict[str, Any], *, extra: str | None = None) -> html.Div:
    provenance = evidence.get("provenance", {})
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        str(evidence.get("evidence_type", "unknown")).replace("_", " "),
                        className="evidence-chip",
                    ),
                    html.Span(
                        f"Source population · {evidence.get('source_population', 'Not stated')}",
                        className="evidence-meta",
                    ),
                    html.Span(
                        f"Grain · {evidence.get('grain', 'Not stated')}", className="evidence-meta"
                    ),
                    html.Span(
                        f"Window · {evidence.get('source_date_or_window', 'Not stated')}",
                        className="evidence-meta",
                    ),
                ],
                className="evidence-row",
            ),
            html.P(
                f"Evidence strength: {evidence.get('evidence_type', 'not stated')}. "
                f"Denominator and uncertainty remain source-specific. {extra or ''}",
                className="evidence-note",
            ),
            html.Details(
                [
                    html.Summary("Method and provenance"),
                    html.P(evidence.get("join_policy", "No join policy supplied.")),
                    html.P(f"Artifact · {provenance.get('artifact', 'Not stated')}"),
                    html.P(f"SHA-256 · {provenance.get('sha256', 'Not stated')}"),
                    html.P(f"Manifest · {provenance.get('manifest', 'Not stated')}"),
                    html.P(
                        "Source manifest · "
                        f"{provenance.get('source_manifest', 'Not separately supplied')}"
                    )
                    if provenance.get("source_manifest")
                    else html.P("Source manifest · Not separately supplied"),
                ],
                className="method-details",
            ),
        ],
        className="evidence-panel",
    )


def limitation(text: str, *, tone: str = "neutral") -> html.Div:
    return html.Div(
        [html.Strong("Boundary · "), html.Span(text)], className=f"boundary boundary-{tone}"
    )


def metric(label: str, value: str, detail: str) -> html.Div:
    return html.Div([html.Small(label), html.Strong(value), html.Span(detail)], className="metric")


def accessible_table(rows: list[dict[str, Any]], *, title: str, limit: int = 12) -> html.Div:
    if not rows:
        return empty_state(f"No {title.lower()} are available in this evidence release.")
    columns = sorted({str(key) for row in rows[:limit] for key in row})
    return html.Div(
        [
            html.H3(title),
            html.P(
                "Table scrolls horizontally on narrow screens; the text alternative below "
                "contains the same displayed rows.",
                className="table-scroll-note",
            ),
            dash_table.DataTable(  # type: ignore[attr-defined]
                data=rows[:limit],
                columns=[
                    {"name": column.replace("_", " ").title(), "id": column} for column in columns
                ],
                page_size=min(limit, 12),
                sort_action="native",
                style_table={"overflowX": "auto"},
                style_cell={
                    "textAlign": "left",
                    "padding": "10px",
                    "fontFamily": "inherit",
                    "minWidth": "120px",
                    "maxWidth": "260px",
                    "whiteSpace": "normal",
                },
                style_header={"fontWeight": "700", "backgroundColor": "#e8edf5"},
            ),
            html.Details(
                [
                    html.Summary("Accessible text alternative"),
                    html.Ul(
                        [
                            html.Li(" · ".join(f"{k}: {v}" for k, v in row.items()))
                            for row in rows[:limit]
                        ]
                    ),
                ],
                className="table-alternative",
            ),
        ],
        className="table-block",
    )


def chart_with_table(figure: dict[str, Any], rows: list[dict[str, Any]], title: str) -> html.Div:
    return html.Div(
        [
            dcc.Graph(figure=figure, config={"displayModeBar": False, "responsive": True}),
            accessible_table(rows, title=f"{title} · table alternative"),
        ],
        className="chart-block",
    )


def _state_component(kind: str, message: str) -> html.Div:
    return html.Div(
        [html.Strong(kind.title()), html.P(message)],
        className=f"state state-{kind}",
        role="status",
    )


def loading_state() -> html.Div:
    return _state_component("loading", "Loading verified evidence…")


def empty_state(message: str) -> html.Div:
    return _state_component("empty", message)


def error_state(message: str) -> html.Div:
    return _state_component("error", message)


def coverage_note(payload: dict[str, Any]) -> html.P:
    pagination = payload.get("pagination", {})
    shown = len(payload.get("items", []))
    total = pagination.get("total", shown)
    complete = shown >= total
    status = (
        "complete panel"
        if complete
        else "partial page window; use API pagination for the remainder."
    )
    return html.P(
        f"Showing {shown} of {total} rows · {status}",
        className="table-note",
    )


def page_shell(title: str, intro: str, children: list[Any]) -> html.Main:
    return html.Main(
        [
            html.Div([html.H1(title), html.P(intro, className="lede")], className="page-heading"),
            *children,
        ],
        className="page-shell",
    )
