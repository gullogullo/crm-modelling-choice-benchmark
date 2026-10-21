#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUTS = ROOT / "outputs"
FIGURES = ROOT / "figures"
RECORD_ID = "bod:23197d1"

COLORS = {
    "e11_modification": "#31688e",
    "condition": "#35b779",
    "material": "#d2a62c",
    "technique": "#d95f59",
}
TEXT_SIZE_BUMP = 2


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def text(
    x: float,
    y: float,
    value: str,
    *,
    size: int = 15,
    anchor: str = "start",
    weight: str = "normal",
    fill: str = "#20262b",
) -> str:
    rendered_size = size + TEXT_SIZE_BUMP
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        f'font-size="{rendered_size}" font-weight="{weight}" fill="{fill}">'
        f"{esc(value)}</text>"
    )


def box(
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: str = "#ffffff",
    stroke: str = "#718089",
    radius: int = 6,
    stroke_width: float = 1.4,
) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" '
        f'rx="{radius}" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{stroke_width}"/>'
    )


def node(
    x: float,
    y: float,
    label: str,
    *,
    fill: str,
    stroke: str = "#66737b",
    width: int = 112,
) -> list[str]:
    return [
        box(x - width / 2, y - 22, width, 44, fill=fill, stroke=stroke),
        text(x, y + 5, label, size=15, anchor="middle", weight="bold"),
    ]


def routed_arrow(
    points: list[tuple[float, float]],
    *,
    stroke: str = "#66737b",
    stroke_width: float = 1.5,
    marker: str = "arrow-source",
    dash: str | None = None,
) -> str:
    """Draw an arrow through explicit, editable turning points."""
    commands = " ".join(
        ("M" if index == 0 else "L") + f" {x} {y}"
        for index, (x, y) in enumerate(points)
    )
    dash_attribute = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<path d="{commands}" fill="none" stroke="{stroke}" '
        f'stroke-width="{stroke_width}"{dash_attribute} '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'marker-end="url(#{marker})"/>'
    )


def source_graph(column_x: float) -> list[str]:
    object_x = column_x + 340
    component_x = column_x + 340
    evidence_y = 375
    detail_y = 480

    e11_x = column_x + 175
    p44_x = column_x + 520
    p126_x = column_x + 95
    p32_x = column_x + 265
    root_turn_y = 310
    detail_turn_y = 435

    lines = [
        box(object_x - 105, 112, 210, 46, fill="#e8eef1", stroke="#52616a"),
        text(object_x, 141, "Described object", size=17, anchor="middle", weight="bold"),

        box(component_x - 125, 220, 250, 50, fill="#edf2f4"),
        text(component_x, 251, "P46 component structure", size=15, anchor="middle", weight="bold"),

        f'<path d="M {object_x} 158 L {component_x} 220" '
        f'fill="none" stroke="#66737b" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round" '
        f'marker-end="url(#arrow-source)"/>',

        text(object_x + 13, 194, "P46+", size=14, fill="#59656c"),

        routed_arrow(
            [
                (component_x - 62, 270),
                (component_x - 62, root_turn_y),
                (e11_x, root_turn_y),
                (e11_x, evidence_y - 23),
            ]
        ),

        routed_arrow(
            [
                (component_x + 62, 270),
                (component_x + 62, root_turn_y),
                (p44_x, root_turn_y),
                (p44_x, evidence_y - 23),
            ]
        ),

        text(column_x + 170, 301, "P31i", size=14, anchor="end", fill="#59656c"),
        text(column_x + 520, 301, "P44", size=14, fill="#59656c"),

        routed_arrow(
            [
                (e11_x - 28, evidence_y + 23),
                (e11_x - 28, detail_turn_y),
                (p126_x, detail_turn_y),
                (p126_x, detail_y - 23),
            ],
            stroke_width=1.4,
        ),

        routed_arrow(
            [
                (e11_x + 28, evidence_y + 23),
                (e11_x + 28, detail_turn_y),
                (p32_x, detail_turn_y),
                (p32_x, detail_y - 23),
            ],
            stroke_width=1.4,
        ),

        text(column_x + 120, 426, "P126", size=14, anchor="end", fill="#59656c"),
        text(column_x + 250, 426, "P32", size=14, fill="#59656c"),
    ]

    lines.extend(node(e11_x, evidence_y, "16 E11", fill="#dbe9f2", stroke=COLORS["e11_modification"]))
    lines.extend(node(p44_x, evidence_y, "11 P44", fill="#daf0e3", stroke=COLORS["condition"]))
    lines.extend(node(p126_x, detail_y, "2 P126", fill="#faedbf", stroke=COLORS["material"]))
    lines.extend(node(p32_x, detail_y, "4 P32", fill="#f5d9d7", stroke=COLORS["technique"]))

    return lines


def direct_source_e11(column_x: float) -> list[str]:
    object_x = column_x + 340
    event_x = column_x + 75

    return [
        f'<line x1="{object_x - 105}" y1="135" '
        f'x2="{event_x + 56}" y2="135" '
        f'stroke="#66737b" stroke-width="1.6" '
        f'stroke-linecap="round" '
        f'marker-end="url(#arrow-source)"/>',

        text(column_x + 184, 158, "source P31i", size=14, anchor="middle", fill="#59656c"),

        *node(event_x, 135, "1 E11", fill="#dbe9f2", stroke=COLORS["e11_modification"]),
    ]


def index_arcs(column_x: float) -> list[str]:
    object_x = column_x + 340
    e11_x = column_x + 175
    p44_x = column_x + 520
    top_lane_y = 185
    lower_turn_y = 326
    left_lane_x = column_x + 118
    right_lane_x = column_x + 640

    return [
        routed_arrow(
            [
                (object_x - 72, 158),
                (object_x - 72, top_lane_y),
                (left_lane_x, top_lane_y),
                (left_lane_x, lower_turn_y),
                (e11_x - 30, lower_turn_y),
                (e11_x - 30, 352),
            ],
            stroke="#a0447a",
            stroke_width=3,
            marker="arrow-index",
            dash="8 5",
        ),

        routed_arrow(
            [
                (object_x + 72, 158),
                (object_x + 72, top_lane_y),
                (right_lane_x, top_lane_y),
                (right_lane_x, lower_turn_y),
                (p44_x + 30, lower_turn_y),
                (p44_x + 30, 352),
            ],
            stroke="#a0447a",
            stroke_width=3,
            marker="arrow-index",
            dash="8 5",
        ),

        text(column_x + 105, 248, "indexed E11", size=15, anchor="end", fill="#7b2e5b"),
        text(column_x + 500, 248, "indexed condition", size=15, fill="#7b2e5b"),
    ]


def result_strip(
    column_x: float,
    counts: dict[str, int],
    recovered: dict[str, int],
) -> list[str]:
    labels = (
        ("E11", "e11_modification"),
        ("P44", "condition"),
        ("P126", "material"),
        ("P32", "technique"),
    )

    lines = [
        text(column_x + 30, 550, "Object query", size=16, weight="bold"),
        box(column_x + 155, 523, 490, 50, fill="#f7f9fa", stroke="#9aa4aa"),
    ]

    for index, (label, family) in enumerate(labels):
        x = column_x + 175 + index * 121
        suffix = f" (+{recovered[family]})" if recovered[family] else ""

        lines.append(
            text(
                x,
                554,
                f"{label} {counts[family]}{suffix}",
                size=15,
                weight="bold",
                fill=COLORS[family],
            )
        )

    return lines


def generate() -> Path:
    comparison = next(
        row
        for row in read_csv(OUTPUTS / "path_profile_answer_set_comparison.csv")
        if row["record_id"] == RECORD_ID
    )

    trace = [
        row
        for row in read_csv(OUTPUTS / "index_recovered_answer_trace.csv")
        if row["record_id"] == RECORD_ID
    ]

    articulated = json.loads(comparison["answers_fully_articulated_path_profile"])
    indexed = json.loads(comparison["answers_index_profile"])

    articulated_counts = {
        family: len(values)
        for family, values in articulated.items()
    }

    index_counts = {
        family: len(values)
        for family, values in indexed.items()
    }

    recovered_counts = {
        family: index_counts[family] - articulated_counts[family]
        for family in index_counts
    }

    expected = {
        "fully_articulated": {
            "e11_modification": 1,
            "condition": 0,
            "material": 0,
            "technique": 0,
        },
        "index": {
            "e11_modification": 17,
            "condition": 11,
            "material": 2,
            "technique": 4,
        },
    }

    if (
        articulated_counts != expected["fully_articulated"]
        or index_counts != expected["index"]
    ):
        raise ValueError("bod:23197d1 answer counts no longer match the figure specification")

    ledger = next(row for row in trace if row["query_family"] == "condition")

    component_label = json.loads(ledger["source_component_label"])[0].split(" (", 1)[0]
    answer_label = ledger["index_recovered_answer_label"].split(" (", 1)[0]
    rule_id = json.loads(ledger["index_rule_id"])[0]

    width, height = 1500, 790
    left_x, right_x = 34, 762

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',

        "<title>Single-record path and index comparison for bod:23197d1</title>",

        "<defs>",

        '<marker id="arrow-source" viewBox="0 0 12 12" '
        'markerWidth="12" markerHeight="12" '
        'refX="12" refY="6" '
        'orient="auto" markerUnits="userSpaceOnUse" overflow="visible">'
        '<path d="M0,1 L11,6 L0,11 Z" fill="#66737b"/>'
        '</marker>',

        '<marker id="arrow-index" viewBox="0 0 12 12" '
        'markerWidth="13" markerHeight="13" '
        'refX="12" refY="6" '
        'orient="auto" markerUnits="userSpaceOnUse" overflow="visible">'
        '<path d="M0,1 L11,6 L0,11 Z" fill="#a0447a"/>'
        '</marker>',

        "</defs>",

        '<rect width="100%" height="100%" fill="#ffffff"/>',

        '<g font-family="Arial, Helvetica, sans-serif">',

        box(20, 28, 700, 590, stroke="#aab3b8"),
        box(748, 28, 732, 590, stroke="#aab3b8"),

        text(370, 67, "Fully-articulated path profile", size=22, anchor="middle", weight="bold"),
        text(1114, 67, "Retrieval-index profile", size=22, anchor="middle", weight="bold"),

        text(370, 92, RECORD_ID, size=15, anchor="middle", fill="#667078"),
        text(1114, 92, "same record, same object query", size=15, anchor="middle", fill="#667078"),
    ]

    for column_x in (left_x, right_x):
        lines.extend(source_graph(column_x))
        lines.extend(direct_source_e11(column_x))

    lines.extend(index_arcs(right_x))

    lines.extend(
        result_strip(
            left_x,
            articulated_counts,
            {family: 0 for family in recovered_counts},
        )
    )

    lines.extend(
        result_strip(
            right_x,
            index_counts,
            recovered_counts,
        )
    )

    lines.extend(
        [
            text(34, 662, "One index trace", size=21, weight="bold"),

            box(34, 680, 1432, 76, fill="#f7f9fa", stroke="#9aa4aa"),

            text(62, 727, component_label, size=18, weight="bold"),
            text(222, 727, "P44", size=17, fill="#59656c"),
            text(275, 727, answer_label, size=18, weight="bold", fill=COLORS["condition"]),

            text(420, 727, "=>", size=21, weight="bold", fill="#7b2e5b"),

            text(475, 727, "Described object", size=18, weight="bold"),
            text(645, 727, "indexCondition", size=17, fill="#7b2e5b"),
            text(800, 727, answer_label, size=18, weight="bold", fill=COLORS["condition"]),

            text(885, 727, "indexed by", size=17, fill="#59656c"),
            text(995, 727, rule_id, size=17, weight="bold", fill="#7b2e5b"),
        ]
    )

    lines.extend(["</g>", "</svg>"])

    FIGURES.mkdir(parents=True, exist_ok=True)

    output = FIGURES / "single_record_shortcut_comparison.svg"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return output


if __name__ == "__main__":
    generate()
