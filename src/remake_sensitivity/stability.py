from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

from .auc import trapezoidal_auc


def tier1_leave_one_out_auc(
    record_rows: list[dict[str, Any]],
    *,
    run_id: str,
    dataset_id: str,
) -> list[dict[str, Any]]:
    eligible_ids = sorted(
        {
            row["record_id"]
            for row in record_rows
            if row["tier"] == "tier1" and bool(row["eligible"])
        }
    )
    parameters = sorted(
        {
            float(row["parameter"])
            for row in record_rows
            if row["tier"] == "tier1" and bool(row["eligible"])
        }
    )
    by_setting: dict[tuple[str, float], dict[str, Any]] = {}
    for row in record_rows:
        if row["tier"] == "tier1" and bool(row["eligible"]):
            by_setting[(row["record_id"], float(row["parameter"]))] = row
    output = []
    for omitted in [None, *eligible_ids]:
        points = []
        denominator_counts = []
        for parameter in parameters:
            included = [
                by_setting[(record_id, parameter)]
                for record_id in eligible_ids
                if record_id != omitted
            ]
            q1 = sum(int(row["q1"]) for row in included)
            q2 = sum(int(row["q2"]) for row in included)
            recall = q1 / q2 if q2 else None
            denominator_counts.append(q2)
            if recall is not None:
                points.append((parameter, recall))
        output.append(
            {
                "run_id": run_id,
                "dataset_id": dataset_id,
                "omitted_record_id": omitted or "",
                "is_full_sample": omitted is None,
                "eligible_record_count": len(eligible_ids) - int(omitted is not None),
                "maker_linked_count_min": min(denominator_counts, default=0),
                "maker_linked_count_max": max(denominator_counts, default=0),
                "direct_retrieval_recall_auc": trapezoidal_auc(points),
                "point_count": len(points),
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_loo_plot(path: Path, rows: list[dict[str, Any]]) -> None:
    full = next(row for row in rows if row["is_full_sample"])
    omitted = sorted(
        (row for row in rows if not row["is_full_sample"]),
        key=lambda row: float(row["direct_retrieval_recall_auc"]),
    )
    width, height = 900, 560
    left, right, top, bottom = 115, 70, 55, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [float(row["direct_retrieval_recall_auc"]) for row in omitted]
    minimum = min(values + [float(full["direct_retrieval_recall_auc"])])
    maximum = max(values + [float(full["direct_retrieval_recall_auc"])])
    padding = max((maximum - minimum) * 0.15, 0.01)
    x_min, x_max = minimum - padding, maximum + padding

    def sx(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    row_h = plot_h / max(len(omitted), 1)
    full_x = sx(float(full["direct_retrieval_recall_auc"]))
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="19" font-weight="600">Tier 1 direct-recall AUC: leave-one-record-out stability</text>',
        f'<line x1="{full_x:.2f}" y1="{top}" x2="{full_x:.2f}" y2="{top+plot_h}" stroke="#d9480f" stroke-width="2" stroke-dasharray="5 4"/>',
    ]
    for index, row in enumerate(omitted):
        y = top + row_h * (index + 0.5)
        value = float(row["direct_retrieval_recall_auc"])
        svg.append(
            f'<text x="{left-12}" y="{y+4:.2f}" text-anchor="end" font-family="sans-serif" font-size="12">omit {row["omitted_record_id"]}</text>'
        )
        svg.append(
            f'<line x1="{sx(minimum):.2f}" y1="{y:.2f}" x2="{sx(maximum):.2f}" y2="{y:.2f}" stroke="#e9ecef"/>'
        )
        svg.append(
            f'<circle cx="{sx(value):.2f}" cy="{y:.2f}" r="5" fill="#1971c2"/>'
        )
        svg.append(
            f'<text x="{sx(value)+9:.2f}" y="{y+4:.2f}" font-family="sans-serif" font-size="11">{value:.3f}</text>'
        )
    svg.append(
        f'<text x="{full_x+6:.2f}" y="{top-10}" font-family="sans-serif" font-size="11" fill="#d9480f">full sample {float(full["direct_retrieval_recall_auc"]):.3f}</text>'
    )
    svg.append(
        f'<text x="{left+plot_w/2}" y="{height-18}" text-anchor="middle" font-family="sans-serif">weighted trapezoidal AUC</text>'
    )
    svg.append("</svg>")
    path.write_text("\n".join(svg), encoding="utf-8")


def loo_summary(rows: list[dict[str, Any]]) -> dict[str, float]:
    full = float(
        next(row["direct_retrieval_recall_auc"] for row in rows if row["is_full_sample"])
    )
    values = [
        float(row["direct_retrieval_recall_auc"])
        for row in rows
        if not row["is_full_sample"]
    ]
    return {
        "full_auc": full,
        "loo_min_auc": min(values),
        "loo_max_auc": max(values),
        "max_absolute_shift": max(abs(value - full) for value in values),
    }
