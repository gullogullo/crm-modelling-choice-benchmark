from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path


PRIMARY_POLICY_ID = "source_semantics"
DISPLAYED_POLICIES = (
    ("all_roots_split", "all roots split"),
    (PRIMARY_POLICY_ID, "source semantics"),
    ("dated_only", "dated only"),
)
DISPLAYED_QUERIES = (
    "current_treatment_history",
    "current_modification_retrieval",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"required publication input is missing: {path}")
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"required publication input is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"no rows to write for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_macros(path: Path, macros: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(f"\\newcommand{{\\{name}}}{{{value}}}" for name, value in macros.items())
        + "\n",
        encoding="utf-8",
    )


def pct(value: float | str) -> str:
    return f"{100 * float(value):.1f}"


def tex_number(value: float | str, places: int = 1) -> str:
    return f"{float(value):.{places}f}"


def tex_escape(value: object) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in text)


def short_label(label: str) -> str:
    return label.split(" (", 1)[0].strip()


def split_episode_label(label: str) -> str:
    words = short_label(label).split()
    if len(words) <= 1:
        return tex_escape(short_label(label))
    return r"\\".join(tex_escape(word) for word in words)


def join_answer_labels(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return rf"\AnswerPair{{{labels[0]}}}{{{labels[1]}}}"
    return r"\quad+\quad".join(rf"\shortstack{{{label}}}" for label in labels)


def write_example_difference_macros(results_dir: Path, output_dir: Path) -> None:
    evidence = read_csv(results_dir / "record_level_evidence.csv")
    query_results = read_csv(results_dir / "query_results.csv")
    candidates = [
        row
        for row in evidence
        if row["ordering_policy_id"] == PRIMARY_POLICY_ID
        and row["lost_treatment_answers"]
    ]
    if not candidates:
        raise ValueError("no source-semantics divergent example found")
    example = sorted(candidates, key=lambda row: row["record_id"])[0]
    episode_ids = example["episode_ids"].split(" || ")
    episode_labels = [
        split_episode_label(label) for label in example["episode_labels"].split(" || ")
    ]
    episode_label_by_id = dict(zip(episode_ids, episode_labels))

    def labels(answer_values: str) -> str:
        values = [value for value in answer_values.split(" || ") if value]
        return join_answer_labels(
            [episode_label_by_id.get(value, "unlabelled") for value in values]
        )

    answers = {
        (row["profile_id"], row["query_id"]): row
        for row in query_results
        if row["record_id"] == example["record_id"]
    }
    macros = {
        "ExampleRecordId": tex_escape(example["record_id"]),
        "ExamplePolicy": tex_escape(example["ordering_policy_id"]),
        "ExampleRule": tex_escape(example["ordering_rule"]),
        "ExampleQuery": tex_escape("treatment history"),
        "ExampleEpisodeOne": episode_labels[0],
        "ExampleEpisodeTwo": episode_labels[1],
        "ExampleLostEpisode": labels(example["lost_treatment_answers"]),
        "ExamplePersistentCurrent": (
            labels(
                answers[
                    ("persistent_e11", "current_treatment_history")
                ]["answer_values"]
            )
        ),
        "ExamplePersistentLineage": (
            labels(
                answers[
                    ("persistent_e11", "lineage_treatment_history")
                ]["answer_values"]
            )
        ),
        "ExampleSegmentedCurrent": (
            labels(
                answers[
                    ("segmented_e81", "current_treatment_history")
                ]["answer_values"]
            )
        ),
        "ExampleSegmentedLineage": (
            labels(
                answers[
                    ("segmented_e81", "lineage_treatment_history")
                ]["answer_values"]
            )
        ),
    }
    write_macros(output_dir / "example_answer_difference_macros.tex", macros)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare data-backed inputs for the three publication figures."
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("outputs/ligatus/results"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("figures/data"),
    )
    args = parser.parse_args()

    manifest = read_json(args.results_dir / "manifest.json")
    audit = read_csv(args.results_dir / "episode_order_audit.csv")
    metrics = read_csv(args.results_dir / "ordering_policy_metrics.csv")
    loo = read_csv(args.results_dir / "leave_one_record_out.csv")
    policy_records = read_csv(args.results_dir / "ordering_policy_record_results.csv")

    primary_audit = [
        row for row in audit if row["ordering_policy_id"] == PRIMARY_POLICY_ID
    ]
    if not primary_audit:
        raise ValueError(f"no episode-order audit rows for {PRIMARY_POLICY_ID}")

    multi_root = [row for row in primary_audit if int(row["source_root_count"]) > 1]
    rule_counts = Counter(row["ordering_rule_id"] for row in multi_root)
    action_counts = Counter(row["action"] for row in primary_audit)
    macros = {
        "LigatusRecordCount": int(manifest["source_record_count"]),
        "LigatusSingleRootCount": sum(
            int(row["source_root_count"]) == 1 for row in primary_audit
        ),
        "LigatusMultiRootCount": len(multi_root),
        "LigatusCollapsedUnsupportedCount": rule_counts["no_supported_order"],
        "LigatusSemanticSplitCount": rule_counts["previous_repair_before_main_event"],
        "LigatusDateSplitCount": rule_counts["parsed_dates"],
        "LigatusPrimarySplitCount": action_counts["split"],
        "LigatusPrimaryCollapseCount": action_counts["collapse"],
    }
    write_macros(args.output_dir / "ligatus_figure_macros.tex", macros)

    metric_map = {
        (row["policy_id"], row["local_query_id"]): row for row in metrics
    }
    sensitivity_rows: list[dict[str, object]] = []
    for policy_id, label in DISPLAYED_POLICIES:
        for query_id in DISPLAYED_QUERIES:
            metric = metric_map[(policy_id, query_id)]
            sensitivity_rows.append(
                {
                    "policy_id": policy_id,
                    "policy_label": label,
                    "query_id": query_id,
                    "query_label": (
                        "treatment history"
                        if query_id == "current_treatment_history"
                        else "modification retrieval"
                    ),
                    "gap_percent": pct(metric["gap_rate"]),
                    "gap_record_count": metric["gap_record_count"],
                    "record_count": metric["record_count"],
                }
            )
    write_csv(args.output_dir / "boundary_policy_sensitivity.csv", sensitivity_rows)

    record_rows = [
        row
        for row in policy_records
        if row["local_query_id"] == "current_treatment_history"
    ]
    policy_loso_rows: list[dict[str, object]] = []
    for policy_id, label in DISPLAYED_POLICIES:
        rows = [row for row in record_rows if row["policy_id"] == policy_id]
        if not rows:
            raise ValueError(f"no record-level rows for policy {policy_id}")
        record_count = len(rows)
        full_gap_count = sum(row["has_gap"] == "True" for row in rows)
        full_rate = full_gap_count / record_count
        deletion_rates = []
        for omitted in rows:
            omitted_gap = omitted["has_gap"] == "True"
            deletion_rates.append((full_gap_count - int(omitted_gap)) / (record_count - 1))
        mean_rate = sum(deletion_rates) / len(deletion_rates)
        sd_rate = math.sqrt(
            sum((rate - mean_rate) ** 2 for rate in deletion_rates)
            / len(deletion_rates)
        )
        min_rate = min(deletion_rates)
        max_rate = max(deletion_rates)
        policy_loso_rows.append(
            {
                "policy_id": policy_id,
                "policy_label": label,
                "gap_percent": pct(full_rate),
                "loo_mean_percent": pct(mean_rate),
                "loo_sd_percent": pct(sd_rate),
                "loo_min_percent": pct(min_rate),
                "loo_max_percent": pct(max_rate),
                "gap_record_count": full_gap_count,
                "record_count": record_count,
            }
        )
    write_csv(args.output_dir / "boundary_policy_loso.csv", policy_loso_rows)

    profile_comparison = read_csv(args.results_dir / "profile_comparison.csv")
    local_lineage = read_csv(args.results_dir / "local_lineage_metrics.csv")
    current_treatment = next(
        row
        for row in profile_comparison
        if row["query_id"] == "current_treatment_history"
    )
    lineage_treatment = next(
        row
        for row in profile_comparison
        if row["query_id"] == "lineage_treatment_history"
    )
    persistent_local_lineage = next(
        row
        for row in local_lineage
        if row["profile_id"] == "persistent_e11"
        and row["local_query_id"] == "current_treatment_history"
    )
    segmented_local_lineage = next(
        row
        for row in local_lineage
        if row["profile_id"] == "segmented_e81"
        and row["local_query_id"] == "current_treatment_history"
    )
    write_csv(
        args.output_dir / "comparison_summary.csv",
        [
            {
                "comparison": "persistent vs segmented, current-local",
                "gap_percent": pct(current_treatment["divergent_record_rate"]),
                "gap_record_count": current_treatment["divergent_record_count"],
                "record_count": manifest["source_record_count"],
            },
            {
                "comparison": "persistent vs segmented, lineage-wide",
                "gap_percent": pct(lineage_treatment["divergent_record_rate"]),
                "gap_record_count": lineage_treatment["divergent_record_count"],
                "record_count": manifest["source_record_count"],
            },
            {
                "comparison": "persistent, current-local vs lineage-wide",
                "gap_percent": pct(persistent_local_lineage["local_lineage_gap_rate"]),
                "gap_record_count": persistent_local_lineage[
                    "records_with_local_lineage_gap"
                ],
                "record_count": manifest["source_record_count"],
            },
            {
                "comparison": "segmented, current-local vs lineage-wide",
                "gap_percent": pct(segmented_local_lineage["local_lineage_gap_rate"]),
                "gap_record_count": segmented_local_lineage[
                    "records_with_local_lineage_gap"
                ],
                "record_count": manifest["source_record_count"],
            },
        ],
    )

    primary_loo = [
        row
        for row in loo
        if row["local_query_id"] == "current_treatment_history"
    ]
    if not primary_loo:
        raise ValueError("no leave-one-record-out rows for treatment history")
    full = next(row for row in primary_loo if not row["omitted_record_id"])
    deletion_rows = [row for row in primary_loo if row["omitted_record_id"]]
    min_rate = min(float(row["gap_rate"]) for row in deletion_rows)
    max_rate = max(float(row["gap_rate"]) for row in deletion_rows)
    max_shift = max(float(row["absolute_shift_from_full"]) for row in primary_loo)
    write_csv(
        args.output_dir / "source_semantics_loso.csv",
        [
            {
                "policy_label": "source semantics",
                "full_percent": pct(full["gap_rate"]),
                "min_percent": pct(min_rate),
                "max_percent": pct(max_rate),
                "max_shift_pp": tex_number(100 * max_shift, 2),
                "gap_record_count": full["gap_record_count"],
                "record_count": full["record_count"],
            }
        ],
    )
    write_example_difference_macros(args.results_dir, args.output_dir)


if __name__ == "__main__":
    main()
