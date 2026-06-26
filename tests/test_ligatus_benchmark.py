from pathlib import Path

import pytest
import yaml
from rdflib import Graph, Literal, RDF, RDFS, URIRef

from remake_sensitivity.ligatus_adapter import (
    _episode_groups,
    load_ordering_manifest,
    load_records,
)
from remake_sensitivity.ligatus_benchmark import (
    build_profile,
    evaluate_query,
    write_report,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data/ligatus/board_pilot.yaml"
FIXTURE = ROOT / "tests/fixtures/ligatus"


def _mapping():
    config = yaml.safe_load(CONFIG.read_text())
    return {
        key: URIRef(value)
        for key, value in config["canonical_mapping"].items()
    }


def _decision(graph, roots, policy):
    return _episode_groups(
        graph,
        set(roots),
        _mapping(),
        policy_id=policy,
        ordering_manifest=load_ordering_manifest(CONFIG),
    )


def _write_mini_record(tmp_path, roots, *, children=()):
    mapping = _mapping()
    graph = Graph()
    object_node = URIRef("http://example.org/mini/object")
    graph.add((object_node, RDF.type, mapping["object_class"]))
    graph.add(
        (
            object_node,
            mapping["production"],
            URIRef("http://example.org/mini/production"),
        )
    )
    for root_id, label, date in roots:
        root = URIRef(root_id)
        graph.add((root, RDF.type, mapping["modification_class"]))
        graph.add((root, RDFS.label, Literal(label)))
        graph.add((object_node, mapping["modified_by"], root))
        if date:
            timespan = URIRef(f"{root_id}/timespan")
            graph.add((root, mapping["timespan"], timespan))
            graph.add((timespan, mapping["begin"], Literal(date)))
    for child_id, label, parent_id in children:
        child = URIRef(child_id)
        graph.add((child, RDF.type, mapping["modification_class"]))
        graph.add((child, RDFS.label, Literal(label)))
        graph.add((child, mapping["event_parent"], URIRef(parent_id)))
        graph.add((object_node, mapping["modified_by"], child))
    target = tmp_path / "bod/individual-records/mini.rdf"
    target.parent.mkdir(parents=True)
    graph.serialize(target, format="xml")
    return tmp_path


def test_ligatus_adapter_preserves_structured_event_hierarchy():
    record = load_records(CONFIG, FIXTURE)[0]
    assert len(record.events) == 3
    assert len(record.episode_ids) == 2
    assert record.episode_order_basis == "parsed_dates"
    child = next(event for event in record.events if event.event_id.endswith("/child"))
    assert child.hierarchy_depth == 1
    assert child.parent_event_id.endswith("/main")
    assert child.episode_order == 2
    assert child.technique_labels == ("Pasting",)
    assert child.treatment_material_labels == ("Japanese paper",)
    assert child.condition_labels == ("Detached",)


def test_reduced_profiles_create_expected_local_lineage_gap():
    record = load_records(CONFIG, FIXTURE)[0]
    persistent = build_profile(record, "persistent_e11")
    segmented = build_profile(record, "segmented_e81")
    assert len(persistent.identities) == 1
    assert len(segmented.identities) == 3
    persistent_local, _ = evaluate_query(
        persistent, "current_modification_retrieval"
    )
    segmented_local, _ = evaluate_query(
        segmented, "current_modification_retrieval"
    )
    segmented_lineage, _ = evaluate_query(
        segmented, "lineage_modification_retrieval"
    )
    assert persistent_local == segmented_lineage
    assert segmented_local < segmented_lineage


def test_ligatus_material_technique_and_condition_queries_use_structured_crm():
    record = load_records(CONFIG, FIXTURE)[0]
    segmented = build_profile(record, "segmented_e81")
    materials, _ = evaluate_query(
        segmented, "lineage_treatment_material_over_time"
    )
    techniques, _ = evaluate_query(segmented, "lineage_technique_over_time")
    conditions, _ = evaluate_query(
        segmented, "lineage_condition_to_treatment"
    )
    assert any("Japanese paper" in answer for answer in materials)
    assert any("Pasting" in answer for answer in techniques)
    assert any("Detached" in answer for answer in conditions)


def test_undated_unordered_roots_are_collapsed_not_sorted_by_uri():
    graph = Graph()
    first = URIRef("http://example.org/a")
    second = URIRef("http://example.org/b")
    graph.add((first, RDFS.label, Literal("Component Reattachment")))
    graph.add((second, RDFS.label, Literal("Treatment Steps")))
    decision = _decision(graph, {first, second}, "source_semantics")
    assert decision.rule_id == "no_supported_order"
    assert decision.action == "collapse"
    assert len(decision.groups) == 1


def test_previous_repair_semantics_are_auditable_and_optional():
    graph = Graph()
    previous = URIRef("http://example.org/previous")
    main = URIRef("http://example.org/main")
    graph.add((previous, RDFS.label, Literal("Previous repair")))
    graph.add((main, RDFS.label, Literal("Main conservation event")))
    primary = _decision(graph, {previous, main}, "source_semantics")
    strict = _decision(graph, {previous, main}, "dated_only")
    assert [group[1][0] for group in primary.groups] == [previous, main]
    assert primary.rule_id == "previous_repair_before_main_event"
    assert primary.action == "split"
    assert len(strict.groups) == 1
    assert strict.rule_id == "no_supported_order"
    assert strict.action == "collapse"


def test_two_dated_roots_split(tmp_path):
    data_dir = _write_mini_record(
        tmp_path,
        (
            ("http://example.org/mini/old", "Old repair", "1900-01-01"),
            ("http://example.org/mini/new", "New repair", "2000-01-01"),
        ),
    )
    record = load_records(CONFIG, data_dir, order_policy="dated_only")[0]
    assert len(record.episode_ids) == 2
    assert record.ordering_rule_id == "parsed_dates"
    assert record.ordering_action == "split"


def test_two_undated_roots_collapse(tmp_path):
    data_dir = _write_mini_record(
        tmp_path,
        (
            ("http://example.org/mini/a", "Repair A", ""),
            ("http://example.org/mini/b", "Repair B", ""),
        ),
    )
    record = load_records(CONFIG, data_dir, order_policy="source_semantics")[0]
    assert len(record.episode_ids) == 1
    assert record.ordering_rule_id == "no_supported_order"
    assert record.ordering_action == "collapse"


def test_all_roots_split_policy_splits_undated_roots(tmp_path):
    data_dir = _write_mini_record(
        tmp_path,
        (
            ("http://example.org/mini/a", "Repair A", ""),
            ("http://example.org/mini/b", "Repair B", ""),
        ),
    )
    record = load_records(CONFIG, data_dir, order_policy="all_roots_split")[0]
    assert len(record.episode_ids) == 2
    assert record.ordering_rule_id == "all_roots_split"
    assert record.ordering_action == "split"


def test_hypothetical_unordered_root_policy_uses_declared_order(tmp_path):
    data_dir = _write_mini_record(
        tmp_path,
        (
            ("http://example.org/mini/reattachment", "Component Reattachment", ""),
            ("http://example.org/mini/treatment", "Treatment Steps", ""),
        ),
    )
    treatment_first = load_records(
        CONFIG,
        data_dir,
        order_policy="hypothetical_treatment_steps_before_component_reattachment",
    )[0]
    reattachment_first = load_records(
        CONFIG,
        data_dir,
        order_policy="hypothetical_component_reattachment_before_treatment_steps",
    )[0]
    assert treatment_first.episode_labels == (
        "Treatment Steps",
        "Component Reattachment",
    )
    assert reattachment_first.episode_labels == (
        "Component Reattachment",
        "Treatment Steps",
    )


def test_previous_main_pair_splits_only_under_source_semantics(tmp_path):
    data_dir = _write_mini_record(
        tmp_path,
        (
            ("http://example.org/mini/previous", "Previous repair", ""),
            (
                "http://example.org/mini/main",
                "Main conservation event",
                "",
            ),
        ),
    )
    semantic = load_records(
        CONFIG, data_dir, order_policy="source_semantics"
    )[0]
    dated = load_records(CONFIG, data_dir, order_policy="dated_only")[0]
    collapsed = load_records(
        CONFIG, data_dir, order_policy="collapse_all_undated"
    )[0]
    assert len(semantic.episode_ids) == 2
    assert semantic.ordering_rule_id == "previous_repair_before_main_event"
    assert len(dated.episode_ids) == 1
    assert len(collapsed.episode_ids) == 1


def test_three_unordered_roots_collapse(tmp_path):
    data_dir = _write_mini_record(
        tmp_path,
        tuple(
            (f"http://example.org/mini/{name}", f"Repair {name}", "")
            for name in ("a", "b", "c")
        ),
    )
    record = load_records(CONFIG, data_dir, order_policy="source_semantics")[0]
    assert record.source_root_count == 3
    assert len(record.episode_ids) == 1


def test_nested_p9_child_does_not_create_identity_segment(tmp_path):
    data_dir = _write_mini_record(
        tmp_path,
        (("http://example.org/mini/main", "Main repair", "2000-01-01"),),
        children=(
            (
                "http://example.org/mini/child",
                "Nested treatment step",
                "http://example.org/mini/main",
            ),
        ),
    )
    record = load_records(CONFIG, data_dir)[0]
    built = build_profile(record, "segmented_e81")
    assert len(record.events) == 2
    assert len(record.episode_ids) == 1
    assert len(built.identities) == 2


def test_ligatus_report_fails_when_machine_results_are_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        write_report(tmp_path / "summary.md", tmp_path / "missing-results")
