from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .canonical_events import CanonicalRecord


def evaluate_event_kinds(
    records: list[CanonicalRecord], review_path: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    review = yaml.safe_load(review_path.read_text(encoding="utf-8"))
    expected = review["events"]
    rows = []
    labels = set(expected.values())
    confusion = Counter()
    for record in records:
        for event in record.events:
            if event.event_id not in expected:
                continue
            manual = expected[event.event_id]
            predicted = event.event_kind
            labels.add(predicted)
            confusion[(manual, predicted)] += 1
            rows.append(
                {
                    "record_id": record.record_id,
                    "event_id": event.event_id,
                    "event_label": event.event_label,
                    "predicted_event_kind": predicted,
                    "manual_event_kind": manual,
                    "exact_match": predicted == manual,
                }
            )
    class_metrics = {}
    for label in sorted(labels):
        tp = confusion[(label, label)]
        fp = sum(
            count
            for (manual, predicted), count in confusion.items()
            if predicted == label and manual != label
        )
        fn = sum(
            count
            for (manual, predicted), count in confusion.items()
            if manual == label and predicted != label
        )
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        class_metrics[label] = {
            "support": sum(
                count
                for (manual, _), count in confusion.items()
                if manual == label
            ),
            "precision": precision,
            "recall": recall,
        }
    supported = [
        metric for metric in class_metrics.values() if metric["support"]
    ]
    summary = {
        "review_id": review["review_id"],
        "review_version": review["version"],
        "reviewed_record_count": len(review["review_scope"]["record_ids"]),
        "reviewed_event_count": len(rows),
        "accuracy": sum(row["exact_match"] for row in rows) / len(rows),
        "macro_precision": sum(
            metric["precision"] or 0 for metric in supported
        )
        / len(supported),
        "macro_recall": sum(metric["recall"] or 0 for metric in supported)
        / len(supported),
        "class_metrics": class_metrics,
        "warning": "Small purposive single-label review; ambiguous events may legitimately support more than one kind.",
    }
    return rows, summary


def write_outputs(
    csv_path: Path,
    json_path: Path,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
