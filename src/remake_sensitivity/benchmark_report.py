from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .io import write_line_plot


def _profile_for_builder(benchmark: dict[str, Any], builder: str) -> str:
    return next(
        profile_id
        for profile_id, profile in benchmark["profiles"].items()
        if profile["builder"] == builder
    )


def write_benchmark_plots(
    plots_dir: Path,
    benchmark_result: dict[str, Any],
) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    metrics = benchmark_result["metric_rows"]
    benchmark = benchmark_result["benchmark"]
    profiles = benchmark["profiles"]

    for tier in ("tier0", "tier1"):
        series = {}
        for profile_id, profile in profiles.items():
            rows = [
                row
                for row in metrics
                if row["profile_id"] == profile_id and row["tier"] == tier
            ]
            series[profile["label"]] = [
                (
                    float(row["parameter_value"]),
                    float(row["identities_per_source_record"]),
                )
                for row in rows
            ]
        write_line_plot(
            plots_dir / f"benchmark_identity_profiles_{tier}.svg",
            title=f"{tier}: represented identities by modelling profile",
            x_label="k" if tier == "tier0" else "threshold (τ)",
            y_label="identities per eligible record",
            series=series,
            x_tick_format=".0f" if tier == "tier0" else ".2f",
        )

    segmented = _profile_for_builder(benchmark, "segmented_e81")
    e13 = _profile_for_builder(benchmark, "segmented_e81_e13")
    propagated = _profile_for_builder(
        benchmark, "segmented_e81_propagated_p108"
    )
    persistent = _profile_for_builder(benchmark, "persistent_e11")
    coverage_series = {}
    series = (
        (persistent, "direct_retrieval_recall", "persistent: direct"),
        (segmented, "direct_retrieval_recall", "segmented: direct"),
        (segmented, "lineage_maker_retrieved_count", "segmented: native E81"),
        (e13, "e13_attribution_coverage", "segmented + E13: assigned"),
        (propagated, "direct_retrieval_recall", "propagated P108: direct"),
    )
    for profile_id, field, label in series:
        rows = [
            row
            for row in metrics
            if row["profile_id"] == profile_id and row["tier"] == "tier1"
        ]
        x = [float(row["parameter_value"]) for row in rows]
        if field == "lineage_maker_retrieved_count":
            y = [
                float(row[field]) / float(row["maker_linked_count"])
                if row["maker_linked_count"]
                else 0
                for row in rows
            ]
        else:
            y = [float(row[field] or 0) for row in rows]
        coverage_series[label] = list(zip(x, y))
    write_line_plot(
        plots_dir / "benchmark_maker_coverage.svg",
        title="Tier 1 maker-answer coverage by modelling profile",
        x_label="threshold (τ)",
        y_label="share of maker-linked records",
        series=coverage_series,
    )

    tier1_settings = [
        setting
        for setting in benchmark_result["settings"]
        if setting.tier == "tier1"
    ]
    middle = min(
        tier1_settings,
        key=lambda setting: abs(float(setting.parameter_value) - 0.5),
    )
    query_ids = list(benchmark_result["benchmark_query_metadata"]["queries"])
    profile_ids = list(profiles)
    answer_map = defaultdict(set)
    for row in benchmark_result["query_rows"]:
        if row["setting_id"] != middle.setting_id:
            continue
        answer_map[(row["profile_id"], row["query_id"])].update(
            value for value in row["answer_values"].split("|") if value
        )
    matrix = [
        [0.0 for _ in profile_ids]
        for _ in query_ids
    ]
    persistent_answers = {
        query_id: answer_map[(persistent, query_id)] for query_id in query_ids
    }
    for row_index, query_id in enumerate(query_ids):
        for column_index, profile_id in enumerate(profile_ids):
            left = persistent_answers[query_id]
            right = answer_map[(profile_id, query_id)]
            union = left | right
            matrix[row_index][column_index] = (
                len(left & right) / len(union) if union else 1
            )
    cell_w, cell_h = 125, 38
    left, top, right, bottom = 275, 70, 35, 80
    width = left + len(profile_ids) * cell_w + right
    height = top + len(query_ids) * cell_h + bottom
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="18" font-weight="600">Answer overlap with persistent profile ({middle.parameter_name}={middle.parameter_value})</text>',
    ]
    for row_index, query_id in enumerate(query_ids):
        y = top + row_index * cell_h
        svg.append(
            f'<text x="{left - 10}" y="{y + 24}" text-anchor="end" font-family="sans-serif" font-size="11">{query_id}</text>'
        )
        for column_index, profile_id in enumerate(profile_ids):
            value = matrix[row_index][column_index]
            red = int(239 - 174 * value)
            green = int(246 - 105 * value)
            blue = int(255 - 62 * value)
            x = left + column_index * cell_w
            svg.append(
                f'<rect x="{x}" y="{y}" width="{cell_w - 2}" height="{cell_h - 2}" fill="rgb({red},{green},{blue})"/>'
            )
            svg.append(
                f'<text x="{x + cell_w / 2}" y="{y + 24}" text-anchor="middle" font-family="sans-serif" font-size="11">{value:.2f}</text>'
            )
    for column_index, profile_id in enumerate(profile_ids):
        x = left + column_index * cell_w + cell_w / 2
        svg.append(
            f'<text x="{x}" y="{top + len(query_ids) * cell_h + 20}" text-anchor="middle" font-family="sans-serif" font-size="11">{profile_id}</text>'
        )
    svg.append("</svg>")
    (plots_dir / "benchmark_profile_overlap.svg").write_text(
        "\n".join(svg), encoding="utf-8"
    )
