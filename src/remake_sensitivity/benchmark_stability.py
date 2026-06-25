from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any


HEADLINE_QUERY_IDS = (
    "direct_production_maker",
    "e13_assigned_maker",
    "current_segment_modification_history",
    "current_segment_part_history",
)


def divergence_stability(
    query_rows: list[dict[str, Any]],
    divergence_rows: list[dict[str, Any]],
    profile_ids: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pair_count = len(profile_ids) * (len(profile_ids) - 1) // 2
    records_by_query: dict[str, set[str]] = {}
    settings_by_query_record: dict[tuple[str, str], set[str]] = {}
    for row in query_rows:
        query_id = row["query_id"]
        record_id = row["record_id"]
        records_by_query.setdefault(query_id, set()).add(record_id)
        settings_by_query_record.setdefault((query_id, record_id), set()).add(
            row["setting_id"]
        )
    divergence_counts = Counter(
        (row["query_id"], row["record_id"]) for row in divergence_rows
    )
    stability_rows = []
    for query_id in HEADLINE_QUERY_IDS:
        record_ids = sorted(records_by_query.get(query_id, set()))
        denominators = {
            record_id: len(settings_by_query_record[(query_id, record_id)])
            * pair_count
            for record_id in record_ids
        }
        full_denominator = sum(denominators.values())
        full_divergences = sum(
            divergence_counts[(query_id, record_id)]
            for record_id in record_ids
        )
        full_rate = (
            full_divergences / full_denominator if full_denominator else 0
        )
        stability_rows.append(
            {
                "query_id": query_id,
                "omitted_record_id": "",
                "divergent_cases": full_divergences,
                "comparable_cases": full_denominator,
                "divergence_rate": full_rate,
                "absolute_shift_from_full": 0.0,
            }
        )
        for record_id in record_ids:
            denominator = full_denominator - denominators[record_id]
            divergences = (
                full_divergences - divergence_counts[(query_id, record_id)]
            )
            rate = divergences / denominator if denominator else 0
            stability_rows.append(
                {
                    "query_id": query_id,
                    "omitted_record_id": record_id,
                    "divergent_cases": divergences,
                    "comparable_cases": denominator,
                    "divergence_rate": rate,
                    "absolute_shift_from_full": abs(rate - full_rate),
                }
            )
    pair_counts = Counter(
        (
            row["query_id"],
            row["from_profile_id"],
            row["to_profile_id"],
        )
        for row in divergence_rows
    )
    pair_denominators = Counter()
    for row in query_rows:
        if row["profile_id"] != profile_ids[0]:
            continue
        for left_index, left in enumerate(profile_ids):
            for right in profile_ids[left_index + 1 :]:
                pair_denominators[(row["query_id"], left, right)] += 1
    pair_rows = [
        {
            "query_id": query_id,
            "from_profile_id": left,
            "to_profile_id": right,
            "divergent_cases": pair_counts[(query_id, left, right)],
            "comparable_cases": denominator,
            "divergence_rate": (
                pair_counts[(query_id, left, right)] / denominator
                if denominator
                else 0
            ),
        }
        for (query_id, left, right), denominator in sorted(
            pair_denominators.items()
        )
    ]
    return stability_rows, pair_rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
