from pathlib import Path

import yaml
from rdflib import RDF

from remake_sensitivity.benchmark_profiles import (
    CRM,
    EX,
    BenchmarkSetting,
    build_profile_record,
)
from remake_sensitivity.benchmark_queries import evaluate_query
from remake_sensitivity.canonical_events import (
    build_canonical_records,
    canonical_event_rows,
)


ROOT = Path(__file__).resolve().parents[1]


def _fixture():
    main = yaml.safe_load((ROOT / "data/e11e81/config.yaml").read_text())
    benchmark = yaml.safe_load((ROOT / main["benchmark"]["config"]).read_text())
    records = build_canonical_records(
        ROOT / "data/records",
        main["record_ids"],
        vocabulary_path=ROOT
        / benchmark["canonical_events"]["extraction_vocabulary"],
        benchmark_config=benchmark,
    )
    record = next(
        record
        for record in records
        if record.maker is not None and len(record.events) > 1
    )
    return benchmark, records, record


def test_canonical_event_table_has_required_profile_independent_columns():
    _, records, _ = _fixture()
    rows = canonical_event_rows(records)
    assert rows
    assert set(rows[0]) == {
        "record_id",
        "event_id",
        "source_order",
        "parsed_date_interval",
        "event_label",
        "event_description",
        "event_kind",
        "affected_component_labels",
        "source_field",
        "source_reference",
        "extraction_method",
        "extraction_vocabulary_version",
    }


def test_required_profiles_have_distinct_declared_semantics():
    benchmark, _, record = _fixture()
    setting = BenchmarkSetting("tier0", "k", "1")
    built = {
        profile["builder"]: build_profile_record(
            profile_id, profile, record, setting
        )
        for profile_id, profile in benchmark["profiles"].items()
    }
    persistent = built["persistent_e11"]
    segmented = built["segmented_e81"]
    assigned = built["segmented_e81_e13"]
    propagated = built["segmented_e81_propagated_p108"]

    assert len(persistent.objects) == 1
    assert not list(persistent.graph.subjects(RDF.type, CRM.E81_Transformation))
    assert len(segmented.objects) > 1
    assert len(assigned.objects) == len(segmented.objects)
    assert len(propagated.objects) == len(segmented.objects)

    segmented_products = set(
        segmented.graph.objects(None, CRM.P108_has_produced)
    )
    assigned_products = set(assigned.graph.objects(None, CRM.P108_has_produced))
    propagated_products = set(
        propagated.graph.objects(None, CRM.P108_has_produced)
    )
    assert segmented_products == {segmented.original}
    assert assigned_products == {assigned.original}
    assert propagated_products == set(propagated.objects)


def test_e13_assignment_is_explicit_and_custom_lineage_maker_is_absent():
    benchmark, _, record = _fixture()
    setting = BenchmarkSetting("tier0", "k", "1")
    for profile_id, profile in benchmark["profiles"].items():
        built = build_profile_record(profile_id, profile, record, setting)
        assert EX.hasLineageMaker not in set(built.graph.predicates())
    profile_id, profile = next(
        (profile_id, profile)
        for profile_id, profile in benchmark["profiles"].items()
        if profile["builder"] == "segmented_e81_e13"
    )
    built = build_profile_record(profile_id, profile, record, setting)
    assignment = next(
        built.graph.subjects(RDF.type, CRM.E13_Attribute_Assignment)
    )
    for predicate in (
        CRM.P140_assigned_attribute_to,
        CRM.P141_assigned,
        CRM.P177_assigned_property_of_type,
        CRM.P16_used_specific_object,
        CRM.P33_used_specific_technique,
    ):
        assert any(built.graph.objects(assignment, predicate))
    production = next(
        built.graph.objects(assignment, CRM.P140_assigned_attribute_to)
    )
    assert (production, RDF.type, CRM.E12_Production) in built.graph
    assert (
        assignment,
        CRM.P177_assigned_property_of_type,
        CRM.P14_carried_out_by,
    ) in built.graph


def test_native_e81_query_recovers_segmented_maker_without_p108_propagation():
    benchmark, _, record = _fixture()
    profile_id, profile = next(
        (profile_id, profile)
        for profile_id, profile in benchmark["profiles"].items()
        if profile["builder"] == "segmented_e81"
    )
    built = build_profile_record(
        profile_id, profile, record, BenchmarkSetting("tier0", "k", "1")
    )
    assert not evaluate_query("maker_direct", built).answers
    assert evaluate_query("maker_lineage", built).answers == frozenset(
        {record.maker}
    )


def test_query_suite_declares_all_required_families():
    metadata = yaml.safe_load(
        (ROOT / "data/e11e81/benchmark_queries/query_metadata.yaml").read_text()
    )
    assert {query["family"] for query in metadata["queries"].values()} == {
        "maker_direct",
        "maker_lineage",
        "maker_e13",
        "classification_current",
        "classification_lineage",
        "material_component_current",
        "material_component_lineage",
        "modification_history",
        "modification_current_segment",
        "modification_lineage",
        "part_history",
        "part_current_segment",
        "part_lineage",
        "condition_history",
        "condition_current_segment",
        "condition_lineage",
        "attribution_classification_history",
        "attribution_classification_current_segment",
        "attribution_classification_lineage",
    }


def test_non_threshold_scenarios_are_configured_without_record_boundaries():
    benchmark, _, record = _fixture()
    scenarios = benchmark["segmentation_scenarios"]
    assert {
        "no_replacement",
        "event_kind_boundaries",
        "explicit_replacement_only",
        "manual_curator_boundaries",
    } == set(scenarios)
    assert scenarios["manual_curator_boundaries"]["boundaries_by_record"] == {}
