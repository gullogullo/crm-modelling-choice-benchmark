from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def write_csv(
    path: Path,
    rows: list[dict[str, Any]] | tuple[tuple[str, ...], ...],
    headers: list[str] | tuple[str, ...] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text(",".join(headers or []) + "\n", encoding="utf-8")
        return
    if isinstance(rows[0], tuple):
        fieldnames = headers or (
            "query_id",
            "query_label",
            "classification",
            "expected_curve",
            "reason",
        )
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(fieldnames)
            writer.writerows(rows)
        return
    fieldnames = list(headers or rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_line_plot(
    path: Path,
    *,
    title: str,
    x_label: str,
    y_label: str,
    series: dict[str, list[tuple[float, float]]],
    colors: tuple[str, ...] = ("#2667ff", "#f08c00", "#2f9e44", "#7048e8"),
    x_tick_format: str = ".2f",
    y_tick_format: str = ".0f",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 920, 540
    left, right, top, bottom = 80, 220, 55, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    all_points = [point for points in series.values() for point in points]
    max_x = max((x for x, _ in all_points), default=1.0)
    min_x = min((x for x, _ in all_points), default=0.0)
    max_y = max((y for _, y in all_points), default=1.0)
    min_y = min((y for _, y in all_points), default=0.0)
    x_span = max(max_x - min_x, 1e-9)
    y_floor = 0.0 if min_y >= 0 else min_y
    y_span = max(max_y - y_floor, 1.0)

    def sx(x: float) -> float:
        return left + (x - min_x) / x_span * plot_w

    def sy(y: float) -> float:
        return top + plot_h - (y - y_floor) / y_span * plot_h

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#333"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#333"/>',
        f'<text x="{left + plot_w / 2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="19" font-weight="600">{title}</text>',
        f'<text x="{left + plot_w / 2}" y="{height - 18}" text-anchor="middle" font-family="sans-serif">{x_label}</text>',
        f'<text x="20" y="{top + plot_h / 2}" transform="rotate(-90 20 {top + plot_h / 2})" text-anchor="middle" font-family="sans-serif">{y_label}</text>',
    ]
    for tick in range(6):
        value = y_floor + y_span * tick / 5
        y = sy(value)
        svg.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="#ddd"/>'
        )
        svg.append(
            f'<text x="{left - 8}" y="{y + 4:.2f}" text-anchor="end" font-family="sans-serif" font-size="11">{format(value, y_tick_format)}</text>'
        )
    unique_x = sorted({x for x, _ in all_points})
    tick_step = max(1, len(unique_x) // 10)
    for x in unique_x[::tick_step]:
        svg.append(
            f'<text x="{sx(x):.2f}" y="{top + plot_h + 22}" text-anchor="middle" font-family="sans-serif" font-size="11">{format(x, x_tick_format)}</text>'
        )
    for index, (name, points) in enumerate(series.items()):
        color = colors[index % len(colors)]
        coordinates = " ".join(f"{sx(x):.2f},{sy(y):.2f}" for x, y in points)
        svg.append(
            f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="3"/>'
        )
        for x, y in points:
            svg.append(
                f'<circle cx="{sx(x):.2f}" cy="{sy(y):.2f}" r="3.5" fill="{color}"/>'
            )
        legend_y = top + 15 + index * 28
        svg.append(
            f'<line x1="{width - 190}" y1="{legend_y}" x2="{width - 160}" y2="{legend_y}" stroke="{color}" stroke-width="4"/>'
        )
        svg.append(
            f'<text x="{width - 152}" y="{legend_y + 4}" font-family="sans-serif" font-size="12">{name}</text>'
        )
    svg.append("</svg>")
    path.write_text("\n".join(svg), encoding="utf-8")
