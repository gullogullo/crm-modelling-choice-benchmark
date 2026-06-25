from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from .extraction import Record
from .segmentation import Event, segment_tier1


def evaluate_manual_review(
    records: list[Record], review_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, frozenset[str]]]:
    review = yaml.safe_load(review_path.read_text(encoding="utf-8"))
    expected = {
        event_id: frozenset(labels) for event_id, labels in review["events"].items()
    }
    rows = []
    tp = fp = fn = 0
    for record in records:
        for event in record.events:
            if event.event_id not in expected:
                continue
            predicted = set(event.elements)
            manual = set(expected[event.event_id])
            event_tp = len(predicted & manual)
            event_fp = len(predicted - manual)
            event_fn = len(manual - predicted)
            tp += event_tp
            fp += event_fp
            fn += event_fn
            rows.append(
                {
                    "record_id": record.record_id,
                    "event_id": event.event_id,
                    "predicted_labels": "|".join(sorted(predicted)),
                    "manual_labels": "|".join(sorted(manual)),
                    "true_positive_count": event_tp,
                    "false_positive_count": event_fp,
                    "false_negative_count": event_fn,
                    "exact_match": predicted == manual,
                }
            )
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    summary = {
        "review_id": review["review_id"],
        "review_version": review["version"],
        "reviewed_record_count": len(review["review_scope"]["record_ids"]),
        "reviewed_event_count": len(rows),
        "true_positive_count": tp,
        "false_positive_count": fp,
        "false_negative_count": fn,
        "micro_precision": precision,
        "micro_recall": recall,
        "micro_f1": f1,
        "exact_match_event_rate": sum(row["exact_match"] for row in rows) / len(rows),
        "warning": "Small purposive review sample; not a statistical confidence interval.",
    }
    return rows, summary, expected


def reviewed_records(
    records: list[Record], expected: dict[str, frozenset[str]]
) -> list[Record]:
    output = []
    for record in records:
        events = tuple(
            replace(event, elements=expected.get(event.event_id, event.elements))
            for event in record.events
        )
        output.append(replace(record, events=events))
    return output


def tier1_review_sensitivity(
    baseline_records: list[Record],
    alternate_records: list[Record],
    taus: list[float],
) -> list[dict[str, Any]]:
    output = []
    baseline_by_id = {record.record_id: record for record in baseline_records}
    alternate_by_id = {record.record_id: record for record in alternate_records}
    for tau in taus:
        baseline_segments = 0
        alternate_segments = 0
        baseline_eligible = 0
        alternate_eligible = 0
        for record_id in baseline_by_id:
            baseline = baseline_by_id[record_id]
            alternate = alternate_by_id[record_id]
            if baseline.total_elements:
                baseline_eligible += 1
                baseline_segments += len(
                    segment_tier1(
                        baseline.events,
                        tau,
                        total_elements=baseline.total_elements,
                    )
                )
            if alternate.total_elements:
                alternate_eligible += 1
                alternate_segments += len(
                    segment_tier1(
                        alternate.events,
                        tau,
                        total_elements=alternate.total_elements,
                    )
                )
        output.append(
            {
                "parameter_value": f"{tau:.2f}",
                "baseline_eligible_record_count": baseline_eligible,
                "reviewed_eligible_record_count": alternate_eligible,
                "baseline_segment_count": baseline_segments,
                "reviewed_segment_count": alternate_segments,
                "band_min_segment_count": min(baseline_segments, alternate_segments),
                "band_max_segment_count": max(baseline_segments, alternate_segments),
                "absolute_segment_delta": alternate_segments - baseline_segments,
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_review_band_plot(path: Path, rows: list[dict[str, Any]]) -> None:
    width, height = 900, 520
    left, right, top, bottom = 75, 180, 55, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    points = [(float(row["parameter_value"]), row) for row in rows]
    max_y = max(int(row["band_max_segment_count"]) for _, row in points)

    def sx(x: float) -> float:
        return left + x * plot_w

    def sy(y: float) -> float:
        return top + plot_h - y / max_y * plot_h

    upper = " ".join(
        f"{sx(x):.2f},{sy(int(row['band_max_segment_count'])):.2f}"
        for x, row in points
    )
    lower = " ".join(
        f"{sx(x):.2f},{sy(int(row['band_min_segment_count'])):.2f}"
        for x, row in reversed(points)
    )
    baseline = " ".join(
        f"{sx(x):.2f},{sy(int(row['baseline_segment_count'])):.2f}"
        for x, row in points
    )
    reviewed = " ".join(
        f"{sx(x):.2f},{sy(int(row['reviewed_segment_count'])):.2f}"
        for x, row in points
    )
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{left+plot_w/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="19" font-weight="600">Tier 1 extraction-review sensitivity band</text>',
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#333"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="#333"/>',
        f'<polygon points="{upper} {lower}" fill="#bac8ff" opacity="0.55"/>',
        f'<polyline points="{baseline}" fill="none" stroke="#1971c2" stroke-width="3"/>',
        f'<polyline points="{reviewed}" fill="none" stroke="#d9480f" stroke-width="3"/>',
        f'<text x="{width-right+20}" y="{top+20}" font-family="sans-serif" font-size="12" fill="#1971c2">deterministic rules</text>',
        f'<text x="{width-right+20}" y="{top+48}" font-family="sans-serif" font-size="12" fill="#d9480f">5-record review substitution</text>',
        f'<text x="{left+plot_w/2}" y="{height-18}" text-anchor="middle" font-family="sans-serif">threshold (τ)</text>',
    ]
    for tick in range(0, max_y + 1, max(1, max_y // 5)):
        y = sy(tick)
        svg.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left+plot_w}" y2="{y:.2f}" stroke="#e9ecef"/>'
        )
        svg.append(
            f'<text x="{left-8}" y="{y+4:.2f}" text-anchor="end" font-family="sans-serif" font-size="11">{tick}</text>'
        )
    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = sx(tick)
        svg.append(
            f'<text x="{x:.2f}" y="{top+plot_h+22}" text-anchor="middle" font-family="sans-serif" font-size="11">{tick:.2f}</text>'
        )
    svg.append(
        f'<text x="20" y="{top+plot_h/2}" transform="rotate(-90 20 {top+plot_h/2})" text-anchor="middle" font-family="sans-serif">aggregate segments</text>'
    )
    svg.append("</svg>")
    path.write_text("\n".join(svg), encoding="utf-8")
