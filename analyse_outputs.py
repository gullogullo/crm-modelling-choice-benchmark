#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import re
import statistics
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
ANALYSIS = OUTPUTS / "analysis"

FAMILIES = (
    (
        "e11_modification",
        "E11 modifications",
        "index_recovered_e11_modification_count",
    ),
    ("condition", "Conditions", "index_recovered_condition_count"),
    ("material", "Materials", "index_recovered_material_count"),
    ("technique", "Techniques", "index_recovered_technique_count"),
)

COLORS = {
    "e11_modification": "#31688e",
    "condition": "#35b779",
    "material": "#f2c14e",
    "technique": "#d95f59",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def family_statistics(comparison: list[dict[str, str]]) -> list[dict]:
    rows = []
    for family, label, field in FAMILIES:
        counts = [int(row[field]) for row in comparison]
        affected = [count for count in counts if count > 0]
        rows.append(
            {
                "query_family": family,
                "answer_family": label,
                "records_affected": len(affected),
                "total_index_recovered": sum(counts),
                "mean_per_affected_record": statistics.mean(affected) if affected else 0,
                "median_per_affected_record": statistics.median(affected) if affected else 0,
                "max_per_record": max(counts, default=0),
            }
        )
    return rows


def record_distribution(comparison: list[dict[str, str]]) -> list[dict]:
    rows = []
    for source in comparison:
        values = {
            family: int(source[field]) for family, _, field in FAMILIES
        }
        rows.append(
            {
                "record_id": source["record_id"],
                "total_index_recovered_answers": sum(values.values()),
                "index_recovered_e11_modifications": values["e11_modification"],
                "index_recovered_conditions": values["condition"],
                "index_recovered_materials": values["material"],
                "index_recovered_techniques": values["technique"],
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            -row["total_index_recovered_answers"],
            row["record_id"],
        ),
    )


def concentration_rows(distribution: list[dict], limit: int = 10) -> list[dict]:
    return [
        {"rank": rank, **row}
        for rank, row in enumerate(distribution[:limit], start=1)
    ]


def normalize_component_label(label: str) -> str:
    without_context = re.sub(r"\s*\([^()]*\)\s*$", "", label).strip()
    return " ".join(without_context.casefold().split()) or "<unlabelled>"


def trace_distributions(trace: list[dict[str, str]]) -> dict[str, list[dict]]:
    exact = Counter()
    component = Counter()
    component_examples: dict[str, set[str]] = {}
    e11 = Counter()
    rules = Counter()
    family_components = Counter()
    family_rules = Counter()

    for row in trace:
        components = json.loads(row["source_component_label"])
        e11_labels = json.loads(row["source_e11_label"])
        rule_ids = json.loads(row["index_rule_id"])
        exact[
            (
                row["query_family"],
                row["source_component_label"],
                row["source_e11_label"],
                row["index_rule_id"],
            )
        ] += 1
        for label in set(components):
            normalized = normalize_component_label(label)
            component[normalized] += 1
            component_examples.setdefault(normalized, set()).add(label)
            family_components[(row["query_family"], normalized)] += 1
        for label in set(e11_labels):
            e11[label] += 1
        for rule_id in set(rule_ids):
            rules[rule_id] += 1
            family_rules[(row["query_family"], rule_id)] += 1

    exact_rows = [
        {
            "query_family": key[0],
            "source_component_label": key[1],
            "source_e11_label": key[2],
            "index_rule_id": key[3],
            "index_recovered_answer_count": count,
        }
        for key, count in sorted(exact.items(), key=lambda item: (-item[1], item[0]))
    ]
    component_rows = [
        {
            "normalized_component_type": component_type,
            "example_exact_labels": json.dumps(
                sorted(component_examples[component_type])[:5]
            ),
            "index_recovered_answer_component_attribution_count": count,
        }
        for component_type, count in sorted(
            component.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    e11_rows = [
        {
            "source_e11_label": label,
            "index_recovered_answer_e11_attribution_count": count,
        }
        for label, count in e11.most_common()
    ]
    rule_rows = [
        {
            "index_rule_id": rule,
            "index_recovered_answer_count": count,
        }
        for rule, count in rules.most_common()
    ]
    family_component_rows = [
        {
            "query_family": key[0],
            "normalized_component_type": key[1],
            "index_recovered_answer_component_attribution_count": count,
        }
        for key, count in sorted(
            family_components.items(), key=lambda item: (item[0][0], -item[1], item[0][1])
        )
    ]
    family_rule_rows = [
        {
            "query_family": key[0],
            "index_rule_id": key[1],
            "index_recovered_answer_count": count,
        }
        for key, count in sorted(
            family_rules.items(), key=lambda item: (item[0][0], -item[1], item[0][1])
        )
    ]
    return {
        "exact": exact_rows,
        "components": component_rows,
        "e11": e11_rows,
        "rules": rule_rows,
        "family_components": family_component_rows,
        "family_rules": family_rule_rows,
    }


def svg_start(width: int, height: int, description: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        f"<title>{html.escape(description)}</title>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<g font-family="Arial, Helvetica, sans-serif" fill="#202428">',
    ]


def write_record_composition(
    path: Path, distribution: list[dict], stats: list[dict]
) -> None:
    width, height = 1950, 600
    left, top, plot_width, plot_height = 105, 42, 1245, 435
    maximum = max(
        row["total_index_recovered_answers"] for row in distribution
    )
    bar_width = plot_width / len(distribution)
    lines = svg_start(
        width,
        height,
        "Index-recovered answer composition for every Ligatus record",
    )
    stats_by_family = {row["query_family"]: row for row in stats}
    for index, (family, label, _) in enumerate(FAMILIES):
        column = index % 2
        row_index = index // 2
        x = 1375 + column * 330
        y = 140 + row_index * 205
        row = stats_by_family[family]
        lines.append(f'<rect x="{x}" y="{y}" width="22" height="22" fill="{COLORS[family]}"/>')
        lines.append(f'<text x="{x + 32}" y="{y + 22}" font-size="29" font-weight="bold">{html.escape(label)}</text>')
        lines.append(
            f'<text x="{x}" y="{y + 62}" font-size="25">total {row["total_index_recovered"]}</text>'
        )
        lines.append(
            f'<text x="{x}" y="{y + 97}" font-size="25">mean affected {row["mean_per_affected_record"]:.2f}</text>'
        )
        lines.append(
            f'<text x="{x}" y="{y + 132}" font-size="25">median {row["median_per_affected_record"]} · max {row["max_per_record"]}</text>'
        )
    for index, row in enumerate(distribution):
        x = left + index * bar_width
        y = top + plot_height
        values = (
            (
                "e11_modification",
                row["index_recovered_e11_modifications"],
            ),
            ("condition", row["index_recovered_conditions"]),
            ("material", row["index_recovered_materials"]),
            ("technique", row["index_recovered_techniques"]),
        )
        for family, value in values:
            segment_height = plot_height * value / maximum
            y -= segment_height
            lines.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{max(1, bar_width - 0.6):.2f}" height="{segment_height:.2f}" fill="{COLORS[family]}"><title>{html.escape(row["record_id"])}; {family}: {value}; total index-recovered: {row["total_index_recovered_answers"]}</title></rect>'
            )
    lines.append(f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" stroke="#4b5258"/>')
    for tick in range(0, maximum + 1, 10):
        y = top + plot_height - plot_height * tick / maximum
        lines.append(f'<text x="{left - 11}" y="{y + 8:.2f}" text-anchor="end" font-size="24">{tick}</text>')
    for rank in (1, 20, 40, 60, 80, 100, 120, 140, len(distribution)):
        x = left + (rank - 0.5) * bar_width
        lines.append(f'<text x="{x:.2f}" y="{top + plot_height + 34}" text-anchor="middle" font-size="23">{rank}</text>')
    lines.append(f'<text x="28" y="{top + plot_height / 2}" transform="rotate(-90 28 {top + plot_height / 2})" text-anchor="middle" font-size="29">Index-recovered answers</text>')
    lines.append(f'<text x="{left + plot_width / 2}" y="{height - 15}" text-anchor="middle" font-size="29">Records ranked by total index-recovered answers</text>')
    lines.extend(["</g>", "</svg>"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_answer_space_composition(path: Path, rows: list[dict[str, str]]) -> None:
    width, height = 1200, 480
    left, top, plot_width, bar_height = 230, 104, 890, 52
    gap = 30
    maximum = max(
        int(row["documented_uri_level_answer_universe"]) for row in rows
    )
    labels = dict((family, label) for family, label, _ in FAMILIES)
    colors = (
        ("visible_in_fully_articulated_path_profile", "#31688e", "Directly visible"),
        ("index_recovered", "#35b779", "Index-recovered"),
        ("documented_but_outside_implemented_paths", "#a8adb2", "Outside implemented paths"),
    )
    lines = svg_start(
        width,
        height,
        "Documented URI-level answer space by query family",
    )
    for index, (_, color, label) in enumerate(colors):
        x = 230 + index * 285
        lines.append(
            f'<rect x="{x}" y="22" width="17" height="17" fill="{color}"/>'
        )
        lines.append(
            f'<text x="{x + 24}" y="37" font-size="13">{html.escape(label)}</text>'
        )
    by_family = {row["query_family"]: row for row in rows}
    for index, family in enumerate(
        ("e11_modification", "condition", "material", "technique")
    ):
        row = by_family[family]
        y = top + index * (bar_height + gap)
        lines.append(
            f'<text x="{left - 15}" y="{y + 33}" text-anchor="end" font-size="16">{html.escape(labels[family])}</text>'
        )
        x = left
        for field, color, label in colors:
            value = int(row[field])
            segment_width = plot_width * value / maximum
            lines.append(
                f'<rect x="{x:.2f}" y="{y}" width="{segment_width:.2f}" height="{bar_height}" fill="{color}"><title>{html.escape(labels[family])}; {label}: {value}</title></rect>'
            )
            if segment_width >= 32:
                lines.append(
                    f'<text x="{x + segment_width / 2:.2f}" y="{y + 33}" text-anchor="middle" font-size="14" fill="#ffffff">{value}</text>'
                )
            x += segment_width
        universe = int(row["documented_uri_level_answer_universe"])
        lines.append(
            f'<text x="{x + 10:.2f}" y="{y + 33}" font-size="14">{universe}</text>'
        )
    lines.append(
        f'<text x="{left + plot_width / 2}" y="{height - 25}" text-anchor="middle" font-size="15">Distinct URI answers per record, summed across 158 records</text>'
    )
    lines.extend(["</g>", "</svg>"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
        *("| " + " | ".join(str(value) for value in row) + " |" for row in rows),
    ]


def write_report(
    path: Path,
    stats: list[dict],
    concentration: list[dict],
    distributions: dict[str, list[dict]],
    dependency_rows: list[dict],
    recall_rows: list[dict[str, str]],
    answer_space_rows: list[dict[str, str]],
    depth_rows: list[dict[str, str]],
    condition_outside_rows: list[dict[str, str]],
    unaffected_rows: list[dict[str, str]],
    trace_count: int,
) -> None:
    lines = [
        "# Index-Recovered Answer Distribution",
        "",
        "![Per-record index-recovered answer composition](per_record_answer_composition.svg)",
        "",
        "![Documented answer space](documented_answer_space.svg)",
        "",
        "## Answer Families",
        "",
    ]
    lines.extend(
        markdown_table(
            ["Answer family", "Records affected", "Index-recovered", "Mean per affected record", "Median per affected record", "Max"],
            [
                [
                    row["answer_family"],
                    row["records_affected"],
                    row["total_index_recovered"],
                    f"{row['mean_per_affected_record']:.2f}",
                    row["median_per_affected_record"],
                    row["max_per_record"],
                ]
                for row in stats
            ],
        )
    )
    lines.extend(["", "## Conditions Outside the Index", ""])
    lines.extend(
        markdown_table(
            ["Classification", "Conditions", "Share"],
            [
                [
                    row["outside_path_category"],
                    row["condition_count"],
                    f"{float(row['share_of_outside_conditions']):.1%}",
                ]
                for row in condition_outside_rows
            ],
        )
    )
    lines.extend(["", "## Unchanged Records", ""])
    lines.extend(
        markdown_table(
            ["Classification", "Records", "Share of unchanged"],
            [
                [
                    row["classification"],
                    row["record_count"],
                    f"{float(row['share_of_unchanged_records']):.1%}",
                ]
                for row in unaffected_rows
            ],
        )
    )
    lines.extend(
        [
            "",
            "The median uses the conventional definition over affected records only. For an even number of affected records, it is the arithmetic mean of the two central integer counts and may therefore be fractional.",
        ]
    )
    lines.extend(["", "## Concentration", ""])
    lines.extend(
        markdown_table(
            ["Rank", "Record", "Total recovered", "Recovered E11", "Recovered conditions", "Recovered materials", "Recovered techniques"],
            [
                [
                    row["rank"],
                    f"`{row['record_id']}`",
                    row["total_index_recovered_answers"],
                    row["index_recovered_e11_modifications"],
                    row["index_recovered_conditions"],
                    row["index_recovered_materials"],
                    row["index_recovered_techniques"],
                ]
                for row in concentration
            ],
        )
    )
    top_components = distributions["components"][:10]
    lines.extend(["", "## Trace Sources", ""])
    lines.append(
        f"The trace contains {trace_count} URI-level index-recovered answers. Every traced answer is reached through a declared P46 path. Component counts below are answer-component attribution incidences; one answer can contribute to several component types when it has multiple source paths."
    )
    lines.extend(["", "### Leading Component Types", ""])
    lines.extend(
        markdown_table(
            ["Rank", "Normalized component type", "Attribution incidences"],
            [
                [rank, row["normalized_component_type"], row["index_recovered_answer_component_attribution_count"]]
                for rank, row in enumerate(top_components, start=1)
            ],
        )
    )
    lines.extend(["", "### Index Rules", ""])
    lines.extend(
        markdown_table(
            ["Index rule", "Index-recovered answers"],
            [
                [
                    row["index_rule_id"],
                    row["index_recovered_answer_count"],
                ]
                for row in distributions["rules"]
            ],
        )
    )
    ranked_families = sorted(
        stats,
        key=lambda row: (
            -row["total_index_recovered"],
            row["query_family"],
        ),
    )
    lines.extend(["", "### Index Dependence", ""])
    lines.append(
        "All index-recovered answers depend on an index triple justified by a fully articulated P46 path."
    )
    lines.extend(
        ["", *markdown_table(
            [
                "Query family",
                "Records affected",
                "URI-level recovered answers",
                "Component attribution incidences",
                "Component types",
            ],
            [
                [
                    row["query_family"],
                    row["records_affected"],
                    row["uri_level_index_recovered_answers"],
                    row["component_attribution_incidences"],
                    row["distinct_normalized_component_types"],
                ]
                for row in dependency_rows
            ],
        )]
    )
    lines.append("")
    lines.append(
        "By URI-level index-recovered magnitude, the families rank: "
        + ", ".join(
            f"{row['answer_family']} ({row['total_index_recovered']})"
            for row in ranked_families
        )
        + ". This is a distribution within the configured index-materialisation experiment, not a general measure of CIDOC CRM dependency."
    )
    lines.extend(
        [
            "",
            "## Object-Level Recall",
            "",
        ]
    )
    lines.extend(
        markdown_table(
            [
                "Query family",
                "Fully articulated answers",
                "Index-profile answers",
                "Recall",
                "Dark records",
                "Dark / records with answers",
            ],
            [
                [
                    row["query_family"],
                    row["fully_articulated_path_answer_count"],
                    row["index_profile_answer_count"],
                    f"{float(row['object_level_recall']):.1%}",
                    row["dark_record_count"],
                    f"{float(row['dark_record_rate_among_records_with_answers']):.1%}",
                ]
                for row in recall_rows
            ],
        )
    )
    lines.extend(["", "## Documented Answer Space", ""])
    lines.extend(
        markdown_table(
            [
                "Query family",
                "Visible",
                "Index-recovered",
                "Outside paths",
                "URI universe",
            ],
            [
                [
                    row["query_family"],
                    row["visible_in_fully_articulated_path_profile"],
                    row["index_recovered"],
                    row["documented_but_outside_implemented_paths"],
                    row["documented_uri_level_answer_universe"],
                ]
                for row in answer_space_rows
            ],
        )
    )
    lines.extend(["", "## P46 Path Depth", ""])
    lines.extend(
        markdown_table(
            ["Query family", "Minimum P46 depth", "Recovered answers"],
            [
                [
                    row["query_family"],
                    row["minimum_p46_path_depth"],
                    row["index_recovered_answer_count"],
                ]
                for row in depth_rows
            ],
        )
    )
    lines.extend(
        [
            "",
            "Exact four-field trace groupings are in `trace_source_distribution.csv`; normalized component-type and family-specific distributions are separate CSVs. Normalization removes only a final parenthetical record-context suffix, folds case, and collapses whitespace.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def component_dependency_rows(
    stats: list[dict], trace_stats: dict[str, list[dict]]
) -> list[dict]:
    component_by_family = Counter()
    types_by_family: dict[str, set[str]] = {}
    for row in trace_stats["family_components"]:
        family = row["query_family"]
        component_by_family[family] += int(
            row["index_recovered_answer_component_attribution_count"]
        )
        types_by_family.setdefault(family, set()).add(
            row["normalized_component_type"]
        )
    return [
        {
            "query_family": row["query_family"],
            "records_affected": row["records_affected"],
            "uri_level_index_recovered_answers": row[
                "total_index_recovered"
            ],
            "component_attribution_incidences": component_by_family[
                row["query_family"]
            ],
            "distinct_normalized_component_types": len(
                types_by_family.get(row["query_family"], set())
            ),
            "index_dependent_by_construction": True,
        }
        for row in sorted(
            stats,
            key=lambda item: (
                -item["total_index_recovered"],
                item["query_family"],
            ),
        )
    ]


def main() -> None:
    comparison = read_csv(OUTPUTS / "path_profile_answer_set_comparison.csv")
    trace = read_csv(OUTPUTS / "index_recovered_answer_trace.csv")
    recall_rows = read_csv(OUTPUTS / "corpus_level_recall.csv")
    answer_space_rows = read_csv(OUTPUTS / "documented_answer_space.csv")
    depth_rows = read_csv(OUTPUTS / "p46_path_depth_distribution.csv")
    condition_outside_rows = read_csv(
        OUTPUTS / "condition_outside_path_summary.csv"
    )
    unaffected_rows = read_csv(OUTPUTS / "unaffected_record_summary.csv")
    stats = family_statistics(comparison)
    distribution = record_distribution(comparison)
    concentration = concentration_rows(distribution)
    trace_stats = trace_distributions(trace)
    dependency_rows = component_dependency_rows(stats, trace_stats)

    ANALYSIS.mkdir(parents=True, exist_ok=True)
    write_csv(ANALYSIS / "answer_family_distribution.csv", stats)
    write_csv(
        ANALYSIS / "record_index_recovery_distribution.csv", distribution
    )
    write_csv(
        ANALYSIS / "top_10_index_recovery_concentration.csv",
        concentration,
    )
    write_csv(ANALYSIS / "trace_source_distribution.csv", trace_stats["exact"])
    write_csv(ANALYSIS / "component_type_distribution.csv", trace_stats["components"])
    write_csv(ANALYSIS / "source_e11_label_distribution.csv", trace_stats["e11"])
    write_csv(
        ANALYSIS / "index_rule_distribution.csv",
        trace_stats["rules"],
    )
    write_csv(
        ANALYSIS / "component_dependency_by_family.csv", dependency_rows
    )
    write_csv(
        ANALYSIS / "family_component_type_distribution.csv",
        trace_stats["family_components"],
    )
    write_csv(
        ANALYSIS / "family_index_rule_distribution.csv",
        trace_stats["family_rules"],
    )
    write_record_composition(
        ANALYSIS / "per_record_answer_composition.svg", distribution, stats
    )
    write_answer_space_composition(
        ANALYSIS / "documented_answer_space.svg", answer_space_rows
    )
    write_report(
        ANALYSIS / "distribution_report.md",
        stats,
        concentration,
        trace_stats,
        dependency_rows,
        recall_rows,
        answer_space_rows,
        depth_rows,
        condition_outside_rows,
        unaffected_rows,
        len(trace),
    )


if __name__ == "__main__":
    main()
