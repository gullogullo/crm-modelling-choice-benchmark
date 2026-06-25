from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from .metric_definitions import AUC_METRICS, INTEGRATION_METHOD


def trapezoidal_auc(points: list[tuple[float, float]]) -> float:
    points = sorted(points)
    return sum(
        (right_x - left_x) * (left_y + right_y) / 2
        for (left_x, left_y), (right_x, right_y) in zip(points, points[1:])
    )


def generate_auc(config_path: Path) -> list[dict[str, Any]]:
    root = Path.cwd()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    paths = config["results"]
    with (root / paths["normalized_metrics"]).open(
        newline="", encoding="utf-8"
    ) as handle:
        rows = list(csv.DictReader(handle))
    manifest = json.loads((root / paths["manifest"]).read_text(encoding="utf-8"))
    grouped: dict[tuple[str, str, str, str], list[tuple[float, float]]] = defaultdict(list)
    for row in rows:
        if row["parameter_value_normalized"] == "":
            continue
        for metric in AUC_METRICS:
            if row[metric] != "":
                grouped[
                    (row["tier"], row["tier_role"], row["convention"], metric)
                ].append(
                    (float(row["parameter_value_normalized"]), float(row[metric]))
                )
    output = []
    for (tier, tier_role, convention, metric), points in grouped.items():
        points = sorted(points)
        minimum, maximum = points[0][0], points[-1][0]
        output.append(
            {
                "run_id": manifest["run_id"],
                "dataset_id": config["dataset_id"],
                "tier": tier,
                "tier_role": tier_role,
                "convention": convention,
                "metric_name": metric,
                "auc_trapezoidal": trapezoidal_auc(points),
                "coverage_min_x": minimum,
                "coverage_max_x": maximum,
                "full_unit_interval_covered": minimum == 0.0 and maximum == 1.0,
                "point_count": len(points),
                "integration_method": INTEGRATION_METHOD,
            }
        )
    path = root / paths["auc"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("data/e11e81/config.yaml"))
    args = parser.parse_args()
    generate_auc(args.config)


if __name__ == "__main__":
    main()
