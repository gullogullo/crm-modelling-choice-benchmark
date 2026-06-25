from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph

from .auc import generate_auc
from .benchmark_report import (
    write_benchmark_plots,
)
from .benchmark_runner import run_benchmark
from .audits import (
    event_order_audit,
    maker_link_audit,
    trailing_segment_audit,
)
from .dataset_profile import (
    profile_affected_labels,
    profile_records,
    write_csv as write_profile_csv,
    write_dataset_plots,
    write_summary_json,
)
from .extraction_review import (
    evaluate_manual_review,
    reviewed_records,
    tier1_review_sensitivity,
    write_csv as write_review_csv,
    write_json as write_review_json,
    write_review_band_plot,
)
from .extraction import load_extraction_vocabulary, load_records
from .graph import CRM, EX, build_record_graph, validate_segment_chain
from .io import write_csv
from .metrics import aggregate_query_rows
from .metrics_normalized import (
    generate_authoring_convention_metrics,
    generate_normalized_metrics,
)
from .query_burden import generate_query_burden
from .queries import (
    QUERY_AUDIT,
    q1_current_direct_zero_hop_by_maker,
    q2_current_reachable_zero_or_more_by_maker,
    q2_current_reachable_native_crm,
    q3_transformation_depth_to_current,
    q4_current_same_as_original_segment,
    q5_direct_vs_reachable_gap,
    current_has_lineage_maker,
)
from .segmentation import segment_tier0, segment_tier1, tier0_closed_form
from .run_manifest import create_manifest, write_manifest
from .stability import (
    loo_summary,
    tier1_leave_one_out_auc,
    write_csv as write_loo_csv,
    write_loo_plot,
)


def _taus(minimum: float, maximum: float, step: float) -> list[float]:
    current = Decimal(str(minimum))
    stop = Decimal(str(maximum))
    increment = Decimal(str(step))
    values = []
    while current <= stop:
        values.append(float(current))
        current += increment
    return values


def _evaluate(
    record, tier: str, parameter: str, segments
) -> tuple[dict[str, Any], list[str], Graph]:
    built = build_record_graph(record, segments)
    errors = validate_segment_chain(built.graph, record.record_id)
    row = {
        "tier": tier,
        "parameter": parameter,
        "record_id": record.record_id,
        "eligible": True,
        "event_count": len(record.events),
        "total_elements": record.total_elements,
        "object_count": len(segments),
        "q1": int(q1_current_direct_zero_hop_by_maker(built)),
        "q2": int(q2_current_reachable_zero_or_more_by_maker(built)),
        "q2_crm_native": int(q2_current_reachable_native_crm(built)),
        "q3_depth": q3_transformation_depth_to_current(built),
        "q4": int(q4_current_same_as_original_segment(built)),
        "q5_gap": q5_direct_vs_reachable_gap(built),
    }
    return row, errors, built.graph


def run(config_path: Path) -> None:
    root = Path.cwd()
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    output_dir = root / config["output_dir"]
    results_dir = output_dir / "results"
    plots_dir = output_dir / "plots"
    graphs_dir = output_dir / "graphs"
    result_paths = {
        name: root / relative_path
        for name, relative_path in config.get("results", {}).items()
    }
    for directory in (results_dir, plots_dir, graphs_dir):
        directory.mkdir(parents=True, exist_ok=True)

    vocabulary_path = root / config["extraction"]["vocabulary"]
    manual_review_path = root / config["extraction"]["manual_review"]
    query_metadata_path = root / config["queries"]["metadata"]
    query_metadata = yaml.safe_load(query_metadata_path.read_text(encoding="utf-8"))
    query_paths = [
        query_metadata_path.parent / query["file"]
        for query in query_metadata["queries"].values()
    ]
    benchmark_path = root / config["benchmark"]["config"]
    benchmark_config = yaml.safe_load(benchmark_path.read_text(encoding="utf-8"))
    benchmark_query_metadata_path = root / benchmark_config["query_metadata"]
    benchmark_query_metadata = yaml.safe_load(
        benchmark_query_metadata_path.read_text(encoding="utf-8")
    )
    benchmark_query_paths = [
        benchmark_query_metadata_path.parent / query["file"]
        for query in benchmark_query_metadata["queries"].values()
    ]
    records = load_records(
        root / "data" / "records",
        config["record_ids"],
        vocabulary_path,
    )
    vocabulary = load_extraction_vocabulary(vocabulary_path)
    manifest = create_manifest(
        root,
        config_path,
        [record.source_path for record in records],
        additional_input_paths=[
            vocabulary_path,
            manual_review_path,
            query_metadata_path,
            *query_paths,
            benchmark_path,
            benchmark_query_metadata_path,
            *benchmark_query_paths,
        ],
        input_record_count=len(records),
        pipeline_version=config["pipeline_version"],
        metric_schema_version=config["metric_schema_version"],
    )
    write_manifest(result_paths["manifest"], manifest)
    write_csv(results_dir / "query_audit.csv", QUERY_AUDIT)
    event_order_rows, inversion_rows = event_order_audit(records)
    maker_rows = maker_link_audit(records)
    trailing_rows = trailing_segment_audit(records)
    write_csv(results_dir / "event_order_audit.csv", event_order_rows)
    write_csv(results_dir / "event_order_inversions.csv", inversion_rows)
    write_csv(result_paths["maker_audit"], maker_rows)
    write_csv(results_dir / "tier1_trailing_segment_audit.csv", trailing_rows)

    extraction_rows = [
        {
            "record_id": record.record_id,
            "event_id": event.event_id,
            "position": position,
            "source_section": event.source_section,
            "event_label": event.label,
            "date": event.date,
            "agent": event.agent,
            "affected_elements": "|".join(sorted(event.elements)),
            "atomic_change_count": len(event.elements),
            "description": event.description,
        }
        for record in records
        for position, event in enumerate(record.events, start=1)
    ]
    write_csv(result_paths["event_extraction"], extraction_rows)
    profile_rows, profile_summary = profile_records(records)
    label_profile_rows = profile_affected_labels(records, vocabulary)
    write_profile_csv(result_paths["dataset_profile"], profile_rows)
    write_summary_json(result_paths["dataset_summary"], profile_summary)
    write_profile_csv(result_paths["affected_label_profile"], label_profile_rows)

    rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    tier0_formula_rows: list[dict[str, Any]] = []
    max_events = max(len(record.events) for record in records)
    k_max = config["tier0"]["k_max"] or max_events
    for k in range(config["tier0"]["k_min"], k_max + 1):
        parameter_graph = Graph()
        parameter_graph.bind("crm", CRM)
        parameter_graph.bind("ex", EX)
        for record in records:
            segments = segment_tier0(record.events, k)
            row, errors, graph = _evaluate(record, "tier0", str(k), segments)
            parameter_graph += graph
            rows.append(row)
            tier0_formula_rows.append(
                {
                    "record_id": record.record_id,
                    "event_count": len(record.events),
                    "k": k,
                    "analytic_object_count": tier0_closed_form(len(record.events), k),
                    "observed_object_count": len(segments),
                    "matches": tier0_closed_form(len(record.events), k) == len(segments),
                }
            )
            validation_rows.extend(
                {
                    "tier": "tier0",
                    "parameter": k,
                    "record_id": record.record_id,
                    "message": message,
                }
                for message in errors
            )
        parameter_graph.serialize(
            graphs_dir / f"tier0_k_{k:02d}.ttl", format="turtle"
        )

    tier1 = config["tier1"]
    tau_values = _taus(tier1["tau_min"], tier1["tau_max"], tier1["tau_step"])
    for tau in tau_values:
        parameter = f"{tau:.2f}"
        parameter_graph = Graph()
        parameter_graph.bind("crm", CRM)
        parameter_graph.bind("ex", EX)
        for record in records:
            if record.total_elements == 0:
                rows.append(
                    {
                        "tier": "tier1",
                        "parameter": parameter,
                        "record_id": record.record_id,
                        "eligible": False,
                        "event_count": len(record.events),
                        "total_elements": 0,
                        "object_count": 0,
                        "q1": 0,
                        "q2": 0,
                        "q2_crm_native": 0,
                        "q3_depth": "",
                        "q4": 0,
                        "q5_gap": 0,
                    }
                )
                continue
            segments = segment_tier1(
                record.events,
                tau,
                total_elements=record.total_elements,
                allow_zero_change_boundaries=tier1["allow_zero_change_boundaries"],
            )
            row, errors, graph = _evaluate(record, "tier1", parameter, segments)
            parameter_graph += graph
            rows.append(row)
            validation_rows.extend(
                {
                    "tier": "tier1",
                    "parameter": parameter,
                    "record_id": record.record_id,
                    "message": message,
                }
                for message in errors
            )
        parameter_graph.serialize(
            graphs_dir / f"tier1_tau_{parameter.replace('.', '_')}.ttl",
            format="turtle",
        )

    aggregates = aggregate_query_rows(rows)
    convention_detail_rows: list[dict[str, Any]] = []
    convention_aggregate_rows: list[dict[str, Any]] = []
    settings = [
        ("tier0", str(k), lambda record, k=k: segment_tier0(record.events, k))
        for k in range(config["tier0"]["k_min"], k_max + 1)
    ] + [
        (
            "tier1",
            f"{float(tau):.2f}",
            lambda record, tau=float(tau): segment_tier1(
                record.events,
                tau,
                total_elements=record.total_elements,
                allow_zero_change_boundaries=tier1["allow_zero_change_boundaries"],
            ),
        )
        for tau in tau_values
    ]
    conventions = tuple(config["authoring_conventions"])
    for tier_name, parameter, segmenter in settings:
        eligible_records = [
            record
            for record in records
            if tier_name == "tier0" or record.total_elements > 0
        ]
        for convention in conventions:
            retrieved = 0
            maker_linked = 0
            for record in eligible_records:
                segments = segmenter(record)
                built = build_record_graph(
                    record, segments, authoring_convention=convention
                )
                maker_linked += int(built.maker is not None)
                answer = (
                    current_has_lineage_maker(built)
                    if convention == "separate_lineage_maker"
                    else q1_current_direct_zero_hop_by_maker(built)
                )
                retrieved += int(answer)
                convention_detail_rows.append(
                    {
                        "tier": tier_name,
                        "parameter": parameter,
                        "convention": convention,
                        "record_id": record.record_id,
                        "maker_linked": built.maker is not None,
                        "current_retrieved": answer,
                    }
                )
            convention_aggregate_rows.append(
                {
                    "tier": tier_name,
                    "parameter": parameter,
                    "convention": convention,
                    "maker_linked_records": maker_linked,
                    "retrieved_current_objects": retrieved,
                }
            )
    write_csv(results_dir / "tier0_closed_form.csv", tier0_formula_rows)
    write_csv(result_paths["record_queries"], rows)
    write_csv(result_paths["aggregate_sweep"], aggregates)
    write_csv(results_dir / "authoring_convention_by_record.csv", convention_detail_rows)
    write_csv(result_paths["authoring_conventions"], convention_aggregate_rows)
    if validation_rows:
        write_csv(result_paths["graph_validation"], validation_rows)
    else:
        result_paths["graph_validation"].write_text(
            "tier,parameter,record_id,message\n", encoding="utf-8"
        )
    write_dataset_plots(plots_dir, profile_summary, rows, label_profile_rows)
    normalized_rows = generate_normalized_metrics(config_path)
    convention_metric_rows = generate_authoring_convention_metrics(
        config_path, normalized_rows
    )
    generate_auc(config_path)
    generate_query_burden(config_path)
    loo_rows = tier1_leave_one_out_auc(
        rows,
        run_id=manifest["run_id"],
        dataset_id=config["dataset_id"],
    )
    write_loo_csv(result_paths["loo_auc"], loo_rows)
    write_loo_plot(plots_dir / "tier1_loo_auc.svg", loo_rows)
    review_rows, review_summary, expected_labels = evaluate_manual_review(
        records, manual_review_path
    )
    write_review_csv(result_paths["extraction_review"], review_rows)
    write_review_json(result_paths["extraction_review_summary"], review_summary)
    alternate_records = reviewed_records(records, expected_labels)
    review_sensitivity_rows = tier1_review_sensitivity(
        records, alternate_records, tau_values
    )
    write_review_csv(
        result_paths["tier1_review_sensitivity"],
        review_sensitivity_rows,
    )
    write_review_band_plot(
        plots_dir / "tier1_extraction_review_band.svg",
        review_sensitivity_rows,
    )
    if config["benchmark"].get("enabled", True):
        benchmark_result = run_benchmark(
            root,
            config,
            benchmark_path,
            manifest,
        )
        write_benchmark_plots(plots_dir, benchmark_result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("data/e11e81/config.yaml"),
    )
    parser.add_argument(
        "--allow-frozen-rerun",
        action="store_true",
        help="Explicitly regenerate the frozen R01-R20 demonstration outputs.",
    )
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    if config.get("frozen") and not args.allow_frozen_rerun:
        parser.error(
            "R01-R20 is frozen. Use the freeze artifacts or pass "
            "--allow-frozen-rerun explicitly."
        )
    run(args.config)


if __name__ == "__main__":
    main()
