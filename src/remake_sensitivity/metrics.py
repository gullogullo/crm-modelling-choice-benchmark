from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def aggregate_query_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["tier"], row["parameter"])].append(row)

    output = []
    for (tier, parameter), items in sorted(grouped.items()):
        eligible = [item for item in items if item["eligible"]]
        output.append(
            {
                "tier": tier,
                "parameter": parameter,
                "eligible_records": len(eligible),
                "object_count": sum(item["object_count"] for item in eligible),
                "Q1_direct_current_count": sum(item["q1"] for item in eligible),
                "Q2_zero_or_more_reachable_control_count": sum(
                    item["q2"] for item in eligible
                ),
                "Q2_crm_native_reachable_control_count": sum(
                    item["q2_crm_native"] for item in eligible
                ),
                "Q3_mean_depth": (
                    sum(item["q3_depth"] for item in eligible) / len(eligible)
                    if eligible
                    else ""
                ),
                "Q4_current_is_original_count": sum(item["q4"] for item in eligible),
                "Q5_direct_vs_reachable_gap": sum(item["q5_gap"] for item in eligible),
            }
        )
    return output


REACHABLE_CONTROL_LABEL = "Zero-or-more reachable-maker control curve"
REACHABLE_CONTROL_DEFINITION = (
    "The count of current objects reachable from a directly produced segment by "
    "ex:precedesSegment*, including the zero-hop case."
)
REACHABLE_CONTROL_WARNING = (
    "If this curve is not flat across the sweep, inspect graph-construction errors, "
    "missing maker links, missing production events, or broken segment chains."
)
