from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


METRIC_COLUMNS = (
    "segment_count",
    "q1_count",
    "q2_count",
    "identities_per_eligible_record",
    "mean_excess_identity",
    "direct_retrieval_recall",
    "lineage_dependence_rate",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _metric_map(results_dir: Path) -> dict[tuple[str, str, str, str], float]:
    rows = _read_csv(results_dir / "normalized_metrics_by_parameter.csv")
    output = {}
    for row in rows:
        for metric in METRIC_COLUMNS:
            if row.get(metric, "") != "":
                output[
                    (
                        row["tier"],
                        row["parameter_value"],
                        row.get("convention", ""),
                        metric,
                    )
                ] = float(row[metric])
    return output


def reconcile_runs(
    current_root: Path,
    previous_root: Path | None,
) -> list[dict[str, Any]]:
    current_results = current_root / "results"
    current_manifest = json.loads(
        (current_results / "run_manifest.json").read_text(encoding="utf-8")
    )
    current = _metric_map(current_results)
    if previous_root is None:
        return []
    previous_results = previous_root / "results"
    previous_manifest = json.loads(
        (previous_results / "run_manifest.json").read_text(encoding="utf-8")
    )
    previous = _metric_map(previous_results)
    rows = []
    for key in sorted(set(current) | set(previous)):
        tier, parameter, convention, metric = key
        current_value = current.get(key)
        previous_value = previous.get(key)
        delta = (
            current_value - previous_value
            if current_value is not None and previous_value is not None
            else None
        )
        relative = (
            delta / previous_value
            if delta is not None and previous_value not in (None, 0)
            else None
        )
        status = "unchanged" if delta == 0 else "changed"
        rows.append(
            {
                "metric_id": metric,
                "tier": tier,
                "parameter": parameter,
                "convention": convention,
                "current_value": current_value,
                "previous_value": previous_value,
                "absolute_delta": delta,
                "relative_delta": relative,
                "input_hash_changed": current_manifest["input_data_hash"]
                != previous_manifest["input_data_hash"],
                "config_hash_changed": current_manifest["config_hash"]
                != previous_manifest["config_hash"],
                "code_hash_changed": current_manifest["code_hash"]
                != previous_manifest["code_hash"],
                "status": status,
            }
        )
    return rows


def write_reconciliation(
    current_root: Path,
    previous_root: Path | None,
    rows: list[dict[str, Any]],
) -> None:
    results_path = current_root / "results" / "run_reconciliation.csv"
    headers = (
        "metric_id",
        "tier",
        "parameter",
        "convention",
        "current_value",
        "previous_value",
        "absolute_delta",
        "relative_delta",
        "input_hash_changed",
        "config_hash_changed",
        "code_hash_changed",
        "status",
    )
    with results_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    rows = reconcile_runs(args.current, args.previous)
    write_reconciliation(args.current, args.previous, rows)


if __name__ == "__main__":
    main()
