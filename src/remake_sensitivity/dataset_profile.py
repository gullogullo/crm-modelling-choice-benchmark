from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .extraction import Record


def profile_records(records: list[Record]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    for record in records:
        data = yaml.safe_load(record.source_path.read_text(encoding="utf-8"))
        historical = data.get("historical_states") or []
        restoration = data.get("restoration_events") or []
        source_events = len(historical) + len(restoration)
        rows.append(
            {
                "record_id": record.record_id,
                "has_historical_states": bool(historical),
                "historical_state_count": len(historical),
                "has_restoration_events": bool(restoration),
                "restoration_event_count": len(restoration),
                "source_documented_event_count": source_events,
                "pipeline_event_count": len(record.events),
                "uses_synthetic_creation": source_events == 0,
                "distinct_affected_label_count": record.total_elements,
                "maker_linked": record.maker is not None,
            }
        )
    source_depths = [row["source_documented_event_count"] for row in rows]
    pipeline_depths = [row["pipeline_event_count"] for row in rows]
    summary = {
        "source_record_count": len(rows),
        "records_with_historical_states": sum(
            row["has_historical_states"] for row in rows
        ),
        "records_with_restoration_events": sum(
            row["has_restoration_events"] for row in rows
        ),
        "records_with_both_event_sections": sum(
            row["has_historical_states"] and row["has_restoration_events"]
            for row in rows
        ),
        "records_with_any_source_events": sum(
            row["source_documented_event_count"] > 0 for row in rows
        ),
        "records_using_synthetic_creation": sum(
            row["uses_synthetic_creation"] for row in rows
        ),
        "historical_state_count": sum(row["historical_state_count"] for row in rows),
        "restoration_event_count": sum(
            row["restoration_event_count"] for row in rows
        ),
        "source_documented_event_count": sum(source_depths),
        "pipeline_event_count": sum(pipeline_depths),
        "source_event_depth_mean": statistics.mean(source_depths) if rows else None,
        "source_event_depth_median": statistics.median(source_depths) if rows else None,
        "source_event_depth_max": max(source_depths, default=0),
        "pipeline_event_depth_mean": statistics.mean(pipeline_depths) if rows else None,
        "source_event_depth_histogram": dict(sorted(Counter(source_depths).items())),
    }
    return rows, summary


def profile_affected_labels(
    records: list[Record], vocabulary: dict[str, Any]
) -> list[dict[str, Any]]:
    counts = Counter(
        label for record in records for event in record.events for label in event.elements
    )
    event_coverage = Counter(
        label
        for record in records
        for event in record.events
        for label in set(event.elements)
    )
    rows = []
    configured_labels = list(vocabulary["labels"]) + [
        vocabulary["generic_change_label"],
        vocabulary["creation_label"],
    ]
    for label in configured_labels:
        rows.append(
            {
                "label": label,
                "configured_lexical_cues": "|".join(
                    vocabulary["labels"].get(label, [])
                ),
                "event_occurrence_count": event_coverage[label],
                "total_assignment_count": counts[label],
                "is_generic_fallback": label == vocabulary["generic_change_label"],
                "is_creation_marker": label == vocabulary["creation_label"],
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_summary_json(path: Path, summary: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _histogram_svg(
    path: Path,
    *,
    title: str,
    x_label: str,
    histogram: dict[int, int],
    color: str,
) -> None:
    width, height = 820, 460
    left, right, top, bottom = 75, 35, 55, 75
    plot_w, plot_h = width - left - right, height - top - bottom
    keys = list(range(min(histogram, default=0), max(histogram, default=0) + 1))
    max_count = max(histogram.values(), default=1)
    slot = plot_w / max(len(keys), 1)
    bar_w = slot * 0.68
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="19" font-weight="600">{title}</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#333"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#333"/>',
    ]
    for key_index, key in enumerate(keys):
        count = histogram.get(key, 0)
        height_value = plot_h * count / max_count
        x = left + key_index * slot + (slot - bar_w) / 2
        y = top + plot_h - height_value
        svg.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{height_value:.2f}" fill="{color}"/>'
        )
        svg.append(
            f'<text x="{x + bar_w/2:.2f}" y="{y - 6:.2f}" text-anchor="middle" font-family="sans-serif" font-size="12">{count}</text>'
        )
        svg.append(
            f'<text x="{x + bar_w/2:.2f}" y="{top + plot_h + 22}" text-anchor="middle" font-family="sans-serif" font-size="12">{key}</text>'
        )
    svg.append(
        f'<text x="{left + plot_w/2}" y="{height - 18}" text-anchor="middle" font-family="sans-serif">{x_label}</text>'
    )
    svg.append(
        f'<text x="20" y="{top + plot_h/2}" transform="rotate(-90 20 {top + plot_h/2})" text-anchor="middle" font-family="sans-serif">records</text>'
    )
    svg.append("</svg>")
    path.write_text("\n".join(svg), encoding="utf-8")


def write_dataset_plots(
    plots_dir: Path,
    profile_summary: dict[str, Any],
    query_rows: list[dict[str, Any]],
    label_rows: list[dict[str, Any]],
) -> None:
    _histogram_svg(
        plots_dir / "dataset_event_depth_histogram.svg",
        title="Documented event depth by source record",
        x_label="historical_states + restoration_events",
        histogram={
            int(key): int(value)
            for key, value in profile_summary["source_event_depth_histogram"].items()
        },
        color="#1971c2",
    )
    selected = {
        ("tier0", "1"): "Tier 0 k=1",
        ("tier0", "4"): "Tier 0 k=4",
        ("tier0", "7"): "Tier 0 k=7",
        ("tier1", "0.00"): "Tier 1 τ=0",
        ("tier1", "0.50"): "Tier 1 τ=.5",
        ("tier1", "1.00"): "Tier 1 τ=1",
    }
    histograms = {}
    for key, label in selected.items():
        values = [
            int(row["object_count"])
            for row in query_rows
            if row["tier"] == key[0]
            and str(row["parameter"]) == key[1]
            and bool(row["eligible"])
        ]
        histograms[label] = Counter(values)
    _segment_histogram_svg(plots_dir / "segment_count_histograms.svg", histograms)
    _label_frequency_svg(plots_dir / "affected_label_frequency.svg", label_rows)


def _segment_histogram_svg(path: Path, histograms: dict[str, Counter]) -> None:
    width, height = 980, 620
    left, right, top, bottom = 80, 230, 60, 80
    plot_w, plot_h = width - left - right, height - top - bottom
    max_segment = max((max(hist, default=1) for hist in histograms.values()), default=1)
    max_count = max(
        (max(hist.values(), default=1) for hist in histograms.values()), default=1
    )
    colors = ("#1971c2", "#74c0fc", "#0b7285", "#d9480f", "#f08c00", "#2b8a3e")
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{left + plot_w/2}" y="30" text-anchor="middle" font-family="sans-serif" font-size="19" font-weight="600">Distribution of represented segments per record</text>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#333"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#333"/>',
    ]
    group_w = plot_w / max_segment
    bar_w = group_w / (len(histograms) + 1)
    for segment in range(1, max_segment + 1):
        center = left + group_w * (segment - 0.5)
        svg.append(
            f'<text x="{center}" y="{top + plot_h + 22}" text-anchor="middle" font-family="sans-serif" font-size="11">{segment}</text>'
        )
        for index, (label, histogram) in enumerate(histograms.items()):
            count = histogram.get(segment, 0)
            h = plot_h * count / max_count
            x = center - len(histograms) * bar_w / 2 + index * bar_w
            y = top + plot_h - h
            svg.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w - 2:.2f}" height="{h:.2f}" fill="{colors[index]}"/>'
            )
    for index, label in enumerate(histograms):
        y = top + 18 + index * 28
        svg.append(
            f'<rect x="{width-right+25}" y="{y-12}" width="18" height="18" fill="{colors[index]}"/>'
        )
        svg.append(
            f'<text x="{width-right+50}" y="{y+2}" font-family="sans-serif" font-size="12">{label}</text>'
        )
    svg.append(
        f'<text x="{left + plot_w/2}" y="{height - 18}" text-anchor="middle" font-family="sans-serif">segments per eligible record</text>'
    )
    svg.append("</svg>")
    path.write_text("\n".join(svg), encoding="utf-8")


def _label_frequency_svg(path: Path, rows: list[dict[str, Any]]) -> None:
    rows = sorted(rows, key=lambda row: int(row["event_occurrence_count"]))
    width, height = 920, 590
    left, right, top, bottom = 180, 75, 55, 50
    plot_w = width - left - right
    bar_h = (height - top - bottom) / max(len(rows), 1)
    maximum = max((int(row["event_occurrence_count"]) for row in rows), default=1)
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="19" font-weight="600">Affected-label assignments by event</text>',
    ]
    for index, row in enumerate(rows):
        value = int(row["event_occurrence_count"])
        y = top + index * bar_h
        width_value = plot_w * value / maximum
        color = "#adb5bd" if bool(row["is_generic_fallback"]) else "#7048e8"
        svg.append(
            f'<text x="{left-10}" y="{y + bar_h*0.68:.2f}" text-anchor="end" font-family="sans-serif" font-size="12">{row["label"]}</text>'
        )
        svg.append(
            f'<rect x="{left}" y="{y+3:.2f}" width="{width_value:.2f}" height="{bar_h-6:.2f}" fill="{color}"/>'
        )
        svg.append(
            f'<text x="{left + width_value + 7:.2f}" y="{y + bar_h*0.68:.2f}" font-family="sans-serif" font-size="11">{value}</text>'
        )
    svg.append("</svg>")
    path.write_text("\n".join(svg), encoding="utf-8")
