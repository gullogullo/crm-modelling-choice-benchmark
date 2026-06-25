from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


def _float_or_none(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def calculate_normalized_metrics(
    *,
    eligible_record_count: int,
    segment_count: int,
    q1_count: int,
    q2_count: int,
) -> dict[str, Any]:
    warnings = []
    identities = _float_or_none(segment_count, eligible_record_count)
    excess = _float_or_none(segment_count - eligible_record_count, eligible_record_count)
    recall = _float_or_none(q1_count, q2_count)
    dependence = _float_or_none(q2_count - q1_count, q2_count)
    if eligible_record_count == 0:
        warnings.append("eligible_record_count is zero")
    if q2_count == 0:
        warnings.append("q2_count is zero")
    return {
        "q1_q2_gap_count": q2_count - q1_count,
        "identities_per_eligible_record": identities,
        "mean_excess_identity": excess,
        "direct_retrieval_recall": recall,
        "lineage_dependence_rate": dependence,
        "denominator_status": "ok" if not warnings else "error",
        "metric_warnings": " | ".join(warnings),
    }


def propagated_equivalence(
    *,
    propagated_retrieved: int,
    strict_retrieved: int,
    q2_count: int,
    q1_count: int,
) -> tuple[float | None, bool]:
    fraction = _float_or_none(
        propagated_retrieved - strict_retrieved, propagated_retrieved
    )
    equivalent = (
        propagated_retrieved == q2_count and strict_retrieved == q1_count
    )
    return fraction, equivalent


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _normalizers(rows: list[dict[str, str]]) -> dict[str, tuple[float, float]]:
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        values[row["tier"]].append(float(row["parameter"]))
    return {tier: (min(items), max(items)) for tier, items in values.items()}


def generate_normalized_metrics(config_path: Path) -> list[dict[str, Any]]:
    root = Path.cwd()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    paths = config["results"]
    aggregate = _read_csv(root / paths["aggregate_sweep"])
    record_rows = _read_csv(root / paths["record_queries"])
    maker_audit = _read_csv(root / paths["maker_audit"])
    manifest = json.loads((root / paths["manifest"]).read_text(encoding="utf-8"))
    maker_by_record = {
        row["record_id"]: row["maker_link_included"].lower() == "true"
        for row in maker_audit
    }
    records_by_setting: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in record_rows:
        records_by_setting[(row["tier"], row["parameter"])].append(row)
    ranges = _normalizers(aggregate)
    output = []
    for row in aggregate:
        tier = row["tier"]
        parameter = row["parameter"]
        tier_config = config["tiers"][tier]
        minimum, maximum = ranges[tier]
        value = float(parameter)
        warnings = []
        normalized = None
        if maximum != minimum:
            normalized = (
                value
                if 0.0 <= minimum and maximum <= 1.0
                else (value - minimum) / (maximum - minimum)
            )
        else:
            warnings.append("single parameter value; normalized parameter is null")
        setting_records = [
            item
            for item in records_by_setting[(tier, parameter)]
            if item["eligible"].lower() == "true"
        ]
        maker_linked_count = sum(
            maker_by_record.get(item["record_id"], False) for item in setting_records
        )
        eligible = int(row["eligible_records"])
        segments = int(row["object_count"])
        q1 = int(row["Q1_direct_current_count"])
        q2 = int(row["Q2_zero_or_more_reachable_control_count"])
        metrics = calculate_normalized_metrics(
            eligible_record_count=eligible,
            segment_count=segments,
            q1_count=q1,
            q2_count=q2,
        )
        if q2 != maker_linked_count:
            warnings.append(
                f"q2_count ({q2}) differs from maker_linked_count ({maker_linked_count})"
            )
        if metrics["metric_warnings"]:
            warnings.append(metrics["metric_warnings"])
        output.append(
            {
                "run_id": manifest["run_id"],
                "dataset_id": config["dataset_id"],
                "tier": tier,
                "tier_role": tier_config["role"],
                "parameter_name": tier_config["parameter_name"],
                "parameter_value": parameter,
                "parameter_value_normalized": normalized,
                "convention": "",
                "source_record_count": manifest["input_record_count"],
                "eligible_record_count": eligible,
                "segment_count": segments,
                "maker_linked_count": maker_linked_count,
                "q1_count": q1,
                "q2_count": q2,
                "q2_crm_native_count": int(
                    row.get("Q2_crm_native_reachable_control_count", q2)
                ),
                "q1_q2_gap_count": metrics["q1_q2_gap_count"],
                "q1_q2_gap_portable_metric": False,
                "identities_per_eligible_record": metrics[
                    "identities_per_eligible_record"
                ],
                "mean_excess_identity": metrics["mean_excess_identity"],
                "direct_retrieval_recall": metrics["direct_retrieval_recall"],
                "lineage_dependence_rate": metrics["lineage_dependence_rate"],
                "denominator_status": (
                    "ok" if not warnings and metrics["denominator_status"] == "ok" else "warning"
                ),
                "metric_warnings": " | ".join(warnings),
            }
        )
    _write_csv(root / paths["normalized_metrics"], output)
    return output


def generate_authoring_convention_metrics(
    config_path: Path, normalized_rows: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    root = Path.cwd()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    paths = config["results"]
    manifest = json.loads((root / paths["manifest"]).read_text(encoding="utf-8"))
    convention_rows = _read_csv(root / paths["authoring_conventions"])
    normalized_rows = normalized_rows or generate_normalized_metrics(config_path)
    normalized_lookup = {
        (row["tier"], str(row["parameter_value"])): row for row in normalized_rows
    }
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in convention_rows:
        groups[(row["tier"], row["parameter"])].append(row)
    output = []
    convention_config = config["authoring_conventions"]
    for (tier, parameter), rows in groups.items():
        base = normalized_lookup[(tier, parameter)]
        strict_rows = [
            row
            for row in rows
            if convention_config[row["convention"]]["semantic_category"] == "strict"
        ]
        strict_retrieved = int(strict_rows[0]["retrieved_current_objects"])
        for row in rows:
            convention = row["convention"]
            category = convention_config[convention]["semantic_category"]
            maker_count = int(row["maker_linked_records"])
            retrieved = int(row["retrieved_current_objects"])
            recall = _float_or_none(retrieved, maker_count)
            gain = _float_or_none(retrieved - strict_retrieved, maker_count)
            warnings = []
            if category == "propagated_production":
                propagated_fraction, equivalent = propagated_equivalence(
                    propagated_retrieved=retrieved,
                    strict_retrieved=strict_retrieved,
                    q2_count=int(base["q2_count"]),
                    q1_count=int(base["q1_count"]),
                )
            else:
                propagated_fraction, equivalent = None, False
            if category == "propagated_production" and not equivalent:
                warnings.append(
                    "propagated retrieval set is not algebraically equivalent to Q2/Q1 gap"
                )
            if maker_count == 0:
                warnings.append("maker_linked_count is zero")
            output.append(
                {
                    "run_id": manifest["run_id"],
                    "dataset_id": config["dataset_id"],
                    "tier": tier,
                    "tier_role": base["tier_role"],
                    "parameter_name": base["parameter_name"],
                    "parameter_value": parameter,
                    "parameter_value_normalized": base[
                        "parameter_value_normalized"
                    ],
                    "convention": convention,
                    "semantic_category": category,
                    "maker_linked_count": maker_count,
                    "retrieved_count": retrieved,
                    "retrieval_recall_by_convention": recall,
                    "retrieval_gain_over_strict": gain,
                    "strict_retrieved_count": strict_retrieved,
                    "q2_count": base["q2_count"],
                    "propagated_extra_fraction": propagated_fraction,
                    "equivalent_to_lineage_dependence_rate": equivalent,
                    "warnings": " | ".join(warnings),
                }
            )
    _write_csv(root / paths["authoring_metrics"], output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("data/e11e81/config.yaml"))
    args = parser.parse_args()
    rows = generate_normalized_metrics(args.config)
    generate_authoring_convention_metrics(args.config, rows)


if __name__ == "__main__":
    main()
