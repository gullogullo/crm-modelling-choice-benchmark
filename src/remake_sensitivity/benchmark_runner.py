from __future__ import annotations

import csv
import hashlib
import itertools
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from .benchmark_profiles import (
    BenchmarkSetting,
    build_profile_record,
    configured_settings,
    serialize_profile_graph,
)
from .benchmark_queries import evaluate_query
from .benchmark_stability import divergence_stability, write_csv as write_stability_csv
from .canonical_events import (
    CanonicalRecord,
    build_canonical_records,
    write_canonical_event_table,
)
from .event_kind_review import evaluate_event_kinds, write_outputs as write_event_kind_outputs
from .query_burden import analyse_query


def _write_csv(path: Path, rows: list[dict[str, Any]], headers=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text(",".join(headers or []) + "\n", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _profile_manifest(
    benchmark: dict[str, Any],
    query_metadata: dict[str, Any],
    settings: list[BenchmarkSetting],
    run_manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "benchmark_id": benchmark["benchmark_id"],
        "benchmark_version": benchmark["benchmark_version"],
        "corpus_role": benchmark.get(
            "corpus_role", "unspecified_benchmark_corpus"
        ),
        "title": benchmark["title"],
        "run_id": run_manifest["run_id"],
        "profiles": benchmark["profiles"],
        "query_suite": query_metadata,
        "parameter_settings": [
            {
                "tier": setting.tier,
                "parameter_name": setting.parameter_name,
                "parameter_value": setting.parameter_value,
                "setting_id": setting.setting_id,
                "scenario_config": setting.scenario_config,
            }
            for setting in settings
        ],
    }


def _eligible(record: CanonicalRecord, setting: BenchmarkSetting) -> bool:
    return setting.tier != "tier1" or record.total_elements > 0


def run_benchmark(
    root: Path,
    main_config: dict[str, Any],
    benchmark_path: Path,
    run_manifest: dict[str, Any],
) -> dict[str, Any]:
    benchmark = yaml.safe_load(benchmark_path.read_text(encoding="utf-8"))
    outputs = benchmark["outputs"]
    vocabulary_path = root / benchmark["canonical_events"]["extraction_vocabulary"]
    records = build_canonical_records(
        root / "data" / "records",
        main_config["record_ids"],
        vocabulary_path=vocabulary_path,
        benchmark_config=benchmark,
    )
    write_canonical_event_table(root / outputs["canonical_event_table"], records)
    event_kind_rows, event_kind_summary = evaluate_event_kinds(
        records, root / benchmark["canonical_events"]["event_kind_review"]
    )
    write_event_kind_outputs(
        root / outputs["event_kind_review"],
        root / outputs["event_kind_review_summary"],
        event_kind_rows,
        event_kind_summary,
    )
    component_review_path = root / "outputs/results/extraction_review_summary.json"
    component_review_summary = (
        json.loads(component_review_path.read_text(encoding="utf-8"))
        if component_review_path.exists()
        else {}
    )
    main_config = {
        **main_config,
        "_record_event_counts": [len(record.events) for record in records],
        "_segmentation_scenarios": benchmark.get(
            "segmentation_scenarios", {}
        ),
    }
    settings = configured_settings(main_config)
    query_metadata_path = root / benchmark["query_metadata"]
    query_metadata = yaml.safe_load(query_metadata_path.read_text(encoding="utf-8"))
    manifest = _profile_manifest(benchmark, query_metadata, settings, run_manifest)
    (root / outputs["profile_manifest"]).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    query_rows = []
    built_lookup = {}
    for profile_id, profile_config in benchmark["profiles"].items():
        for setting in settings:
            built_records = []
            for record in records:
                if not _eligible(record, setting):
                    continue
                built = build_profile_record(
                    profile_id, profile_config, record, setting
                )
                if built is None:
                    continue
                built_records.append(built)
                built_lookup[(profile_id, setting.setting_id, record.record_id)] = built
                for query_id, query_config in query_metadata["queries"].items():
                    evaluation = evaluate_query(query_config["family"], built)
                    query_rows.append(
                        {
                            "run_id": run_manifest["run_id"],
                            "benchmark_id": benchmark["benchmark_id"],
                            "profile_id": profile_id,
                            "profile_label": profile_config["label"],
                            "profile_semantic_category": profile_config[
                                "semantic_category"
                            ],
                            "tier": setting.tier,
                            "parameter_name": setting.parameter_name,
                            "parameter_value": setting.parameter_value,
                            "setting_id": setting.setting_id,
                            "query_id": query_id,
                            "query_family": query_config["family"],
                            "intended_question": query_config[
                                "intended_question"
                            ],
                            "record_id": record.record_id,
                            "answer_count": len(evaluation.answers),
                            "answer_values": "|".join(sorted(evaluation.answers)),
                            "answer_present": bool(evaluation.answers),
                            "runtime_ms": evaluation.runtime_ms,
                            "execution_engine": evaluation.execution_engine,
                        }
                    )
            graph_path = (
                root
                / outputs["profile_graphs"]
                / profile_id
                / f"{setting.setting_id}.ttl"
            )
            serialize_profile_graph(graph_path, built_records)
    _write_csv(root / outputs["query_results"], query_rows)

    result_map = {
        (
            row["profile_id"],
            row["setting_id"],
            row["query_id"],
            row["record_id"],
        ): frozenset(filter(None, row["answer_values"].split("|")))
        for row in query_rows
    }
    metric_rows = _retrieval_metrics(
        benchmark, settings, records, query_rows, built_lookup, run_manifest
    )
    _write_csv(root / outputs["retrieval_metrics"], metric_rows)
    burden_rows = _query_burden_by_profile(
        benchmark,
        settings,
        query_metadata_path,
        query_metadata,
        run_manifest,
    )
    _write_csv(root / outputs["query_burden"], burden_rows)
    delta_rows, divergence_rows = _profile_deltas(
        benchmark,
        settings,
        records,
        query_metadata,
        result_map,
        run_manifest,
    )
    _write_csv(root / outputs["profile_deltas"], delta_rows)
    _write_csv(root / outputs["record_divergence"], divergence_rows)
    stability_rows, pair_divergence_rows = divergence_stability(
        query_rows, divergence_rows, list(benchmark["profiles"])
    )
    write_stability_csv(
        root / outputs["divergence_stability"], stability_rows
    )
    write_stability_csv(
        root / outputs["profile_pair_divergence"], pair_divergence_rows
    )
    return {
        "benchmark": benchmark,
        "benchmark_query_metadata": query_metadata,
        "records": records,
        "settings": settings,
        "query_rows": query_rows,
        "metric_rows": metric_rows,
        "burden_rows": burden_rows,
        "delta_rows": delta_rows,
        "divergence_rows": divergence_rows,
        "stability_rows": stability_rows,
        "pair_divergence_rows": pair_divergence_rows,
        "built_lookup": built_lookup,
        "event_kind_review_summary": event_kind_summary,
        "component_review_summary": component_review_summary,
    }


def _retrieval_metrics(
    benchmark,
    settings,
    records,
    query_rows,
    built_lookup,
    run_manifest,
):
    query_by_key = {
        (row["profile_id"], row["setting_id"], row["query_family"], row["record_id"]): row
        for row in query_rows
    }
    rows = []
    for profile_id, profile_config in benchmark["profiles"].items():
        for setting in settings:
            eligible_records = [
                record for record in records if _eligible(record, setting)
            ]
            built_records = [
                built_lookup[(profile_id, setting.setting_id, record.record_id)]
                for record in eligible_records
            ]
            maker_linked = sum(record.maker is not None for record in eligible_records)
            direct = sum(
                query_by_key[
                    (
                        profile_id,
                        setting.setting_id,
                        "maker_direct",
                        record.record_id,
                    )
                ]["answer_present"]
                for record in eligible_records
            )
            lineage = sum(
                query_by_key[
                    (
                        profile_id,
                        setting.setting_id,
                        "maker_lineage",
                        record.record_id,
                    )
                ]["answer_present"]
                for record in eligible_records
            )
            e13 = sum(
                query_by_key[
                    (
                        profile_id,
                        setting.setting_id,
                        "maker_e13",
                        record.record_id,
                    )
                ]["answer_present"]
                for record in eligible_records
            )
            rows.append(
                {
                    "run_id": run_manifest["run_id"],
                    "benchmark_id": benchmark["benchmark_id"],
                    "profile_id": profile_id,
                    "profile_label": profile_config["label"],
                    "profile_semantic_category": profile_config[
                        "semantic_category"
                    ],
                    "recommended_status": profile_config["recommended_status"],
                    "tier": setting.tier,
                    "parameter_name": setting.parameter_name,
                    "parameter_value": setting.parameter_value,
                    "setting_id": setting.setting_id,
                    "source_record_count": len(records),
                    "eligible_record_count": len(eligible_records),
                    "represented_identity_count": sum(
                        len(built.objects) for built in built_records
                    ),
                    "identities_per_source_record": (
                        sum(len(built.objects) for built in built_records)
                        / len(eligible_records)
                        if eligible_records
                        else None
                    ),
                    "maker_linked_count": maker_linked,
                    "direct_maker_retrieved_count": direct,
                    "lineage_maker_retrieved_count": lineage,
                    "e13_attribution_retrieved_count": e13,
                    "direct_retrieval_recall": (
                        direct / lineage if lineage else None
                    ),
                    "lineage_dependence_rate": (
                        (lineage - direct) / lineage if lineage else None
                    ),
                    "e13_attribution_coverage": (
                        e13 / maker_linked if maker_linked else None
                    ),
                }
            )
    return rows


def _query_burden_by_profile(
    benchmark, settings, metadata_path, metadata, run_manifest
):
    rows = []
    for query_id, query_config in metadata["queries"].items():
        query_path = metadata_path.parent / query_config["file"]
        text = query_path.read_text(encoding="utf-8")
        burden = analyse_query(query_id, text, query_config, set())
        for profile_id, profile_config in benchmark["profiles"].items():
            for setting in settings:
                rows.append(
                    {
                        "run_id": run_manifest["run_id"],
                        "benchmark_id": benchmark["benchmark_id"],
                        "profile_id": profile_id,
                        "tier": setting.tier,
                        "parameter_name": setting.parameter_name,
                        "parameter_value": setting.parameter_value,
                        "setting_id": setting.setting_id,
                        "query_id": query_id,
                        "query_family": query_config["family"],
                        "intended_question": query_config["intended_question"],
                        "primary_for_profile": query_config["family"]
                        == profile_config["primary_maker_query_family"],
                        "parameter_invariant": True,
                        "query_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        **{
                            key: value
                            for key, value in burden.items()
                            if key not in {"query_id", "query_role"}
                        },
                    }
                )
    return rows


def _profile_deltas(
    benchmark,
    settings,
    records,
    query_metadata,
    result_map,
    run_manifest,
):
    delta_rows = []
    divergence_rows = []
    profiles = list(benchmark["profiles"])
    for setting in settings:
        eligible_records = [
            record for record in records if _eligible(record, setting)
        ]
        for left_profile, right_profile in itertools.combinations(profiles, 2):
            for query_id, query_config in query_metadata["queries"].items():
                left_set = {
                    (record.record_id, answer)
                    for record in eligible_records
                    for answer in result_map[
                        (
                            left_profile,
                            setting.setting_id,
                            query_id,
                            record.record_id,
                        )
                    ]
                }
                right_set = {
                    (record.record_id, answer)
                    for record in eligible_records
                    for answer in result_map[
                        (
                            right_profile,
                            setting.setting_id,
                            query_id,
                            record.record_id,
                        )
                    ]
                }
                union = left_set | right_set
                intersection = left_set & right_set
                lost = left_set - right_set
                recovered = right_set - left_set
                delta_rows.append(
                    {
                        "run_id": run_manifest["run_id"],
                        "benchmark_id": benchmark["benchmark_id"],
                        "tier": setting.tier,
                        "parameter_name": setting.parameter_name,
                        "parameter_value": setting.parameter_value,
                        "setting_id": setting.setting_id,
                        "query_id": query_id,
                        "query_family": query_config["family"],
                        "from_profile_id": left_profile,
                        "to_profile_id": right_profile,
                        "from_answer_count": len(left_set),
                        "to_answer_count": len(right_set),
                        "intersection_count": len(intersection),
                        "union_count": len(union),
                        "jaccard_overlap": len(intersection) / len(union)
                        if union
                        else 1.0,
                        "lost_answer_count": len(lost),
                        "recovered_answer_count": len(recovered),
                        "divergent_record_count": len(
                            {record_id for record_id, _ in lost | recovered}
                        ),
                    }
                )
                for record in eligible_records:
                    left_answers = result_map[
                        (
                            left_profile,
                            setting.setting_id,
                            query_id,
                            record.record_id,
                        )
                    ]
                    right_answers = result_map[
                        (
                            right_profile,
                            setting.setting_id,
                            query_id,
                            record.record_id,
                        )
                    ]
                    if left_answers != right_answers:
                        divergence_rows.append(
                            {
                                "run_id": run_manifest["run_id"],
                                "benchmark_id": benchmark["benchmark_id"],
                                "tier": setting.tier,
                                "parameter_name": setting.parameter_name,
                                "parameter_value": setting.parameter_value,
                                "setting_id": setting.setting_id,
                                "query_id": query_id,
                                "query_family": query_config["family"],
                                "from_profile_id": left_profile,
                                "to_profile_id": right_profile,
                                "record_id": record.record_id,
                                "from_answers": "|".join(sorted(left_answers)),
                                "to_answers": "|".join(sorted(right_answers)),
                                "lost_answers": "|".join(
                                    sorted(left_answers - right_answers)
                                ),
                                "recovered_answers": "|".join(
                                    sorted(right_answers - left_answers)
                                ),
                            }
                        )
    return delta_rows, divergence_rows
