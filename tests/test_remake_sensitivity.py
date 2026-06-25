from __future__ import annotations

from pathlib import Path

from rdflib import RDF

from remake_sensitivity.audits import event_order_audit, maker_link_audit
from remake_sensitivity.extraction import Record, load_records
from remake_sensitivity.graph import CRM, EX, build_record_graph, validate_segment_chain
from remake_sensitivity.queries import (
    Q2_SPARQL,
    q1_current_direct_zero_hop_by_maker,
    q2_current_reachable_zero_or_more_by_maker,
    q2_current_reachable_native_crm,
    q3_transformation_depth_to_current,
    current_has_lineage_maker,
)
from remake_sensitivity.segmentation import Event, segment_tier0, segment_tier1


def _events() -> list[Event]:
    return [
        Event("E1", "change", frozenset({"case"})),
        Event("E2", "documented no-change", frozenset()),
        Event("E3", "change", frozenset({"jacks"})),
        Event("E4", "change", frozenset({"keyboard"})),
    ]


def _record(events=None) -> Record:
    return Record(
        record_id="T01",
        label="Toy instrument",
        maker="Toy Maker",
        events=tuple(events or _events()),
        source_path=None,  # type: ignore[arg-type]
    )


def test_tier1_tau_zero_does_not_reset_zero_change_events():
    events = _events()[:3]
    segments = segment_tier1(
        events,
        0.0,
        allow_zero_change_boundaries=False,
    )
    assert [[event.event_id for event in segment.events] for segment in segments] == [
        ["E1"],
        ["E2", "E3"],
    ]


def test_tier1_denominator_is_fixed_from_entire_record_history():
    events = [
        Event("E1", "change", frozenset({"case"})),
        Event("E2", "change", frozenset({"jacks"})),
        Event("E3", "change", frozenset({"case"})),
    ]
    segments = segment_tier1(events, 1.0)
    assert [[event.event_id for event in segment.events] for segment in segments] == [
        ["E1", "E2"],
        ["E3"],
    ]


def test_query_invariance_fully_collapsed_graph():
    record = _record()
    built = build_record_graph(record, segment_tier0(record.events, 4))
    assert len(built.segments) == 1
    assert len(list(built.graph.triples((None, EX.precedesSegment, None)))) == 0
    assert built.current == built.original
    assert q1_current_direct_zero_hop_by_maker(built)
    assert q2_current_reachable_zero_or_more_by_maker(built)
    assert q2_current_reachable_native_crm(built)
    assert q3_transformation_depth_to_current(built) == 0


def test_query_invariance_fragmented_graph():
    record = _record()
    built = build_record_graph(record, segment_tier0(record.events, 1))
    assert len(built.segments) == 4
    assert len(list(built.graph.triples((None, EX.precedesSegment, None)))) == 3
    assert built.current == built.segments[3]
    assert built.original == built.segments[0]
    assert not q1_current_direct_zero_hop_by_maker(built)
    assert q2_current_reachable_zero_or_more_by_maker(built)
    assert q2_current_reachable_native_crm(built)
    assert q3_transformation_depth_to_current(built) == 3


def test_crm_transformation_direction():
    record = _record()
    built = build_record_graph(record, segment_tier0(record.events, 1))
    for old, new in zip(built.segments, built.segments[1:]):
        transformations = [
            trans
            for trans in built.graph.subjects(CRM.P124_transformed, old)
            if (trans, RDF.type, CRM.E81_Transformation) in built.graph
        ]
        assert len(transformations) == 1
        assert (transformations[0], CRM.P123_resulted_in, new) in built.graph
        assert (old, EX.precedesSegment, new) in built.graph


def test_q2_flat_across_all_k():
    record = _record()
    answers = []
    for k in range(1, len(record.events) + 1):
        built = build_record_graph(record, segment_tier0(record.events, k))
        answers.append(q2_current_reachable_zero_or_more_by_maker(built))
        assert q2_current_reachable_native_crm(built)
        assert validate_segment_chain(built.graph, record.record_id) == []
    assert answers == [True] * len(record.events)
    assert "ex:precedesSegment*" in Q2_SPARQL
    assert "ex:precedesSegment+" not in Q2_SPARQL


def test_authoring_conventions_separate_production_from_lineage_maker():
    record = _record()
    segments = segment_tier0(record.events, 1)
    strict = build_record_graph(record, segments)
    propagated = build_record_graph(
        record, segments, authoring_convention="propagated_production"
    )
    lineage = build_record_graph(
        record, segments, authoring_convention="separate_lineage_maker"
    )
    assert not q1_current_direct_zero_hop_by_maker(strict)
    assert q1_current_direct_zero_hop_by_maker(propagated)
    assert not q1_current_direct_zero_hop_by_maker(lineage)
    assert current_has_lineage_maker(lineage)
    production = EX[f"{record.record_id}_production"]
    assert list(lineage.graph.objects(production, CRM.P108_has_produced)) == [
        lineage.original
    ]


def test_corpus_hygiene_audits_expose_current_order_and_maker_boundary():
    records = load_records(
        Path("data/records"), [f"R{index:02d}" for index in range(1, 21)]
    )
    order_rows, inversions = event_order_audit(records)
    maker_rows = maker_link_audit(records)
    assert sum(row["has_parseable_date"] for row in order_rows) == 19
    assert sum(row["parseable_date_count"] for row in order_rows) == 43
    assert inversions == []
    assert sum(row["maker_link_included"] for row in maker_rows) == 15


def test_authoring_sweep_output_covers_full_configured_grids():
    import yaml

    config = yaml.safe_load(Path("data/e11e81/config.yaml").read_text())
    records = load_records(
        Path("data/records"), [f"R{index:02d}" for index in range(1, 21)]
    )
    max_events = max(len(record.events) for record in records)
    tier0_count = max_events - config["tier0"]["k_min"] + 1
    tier1 = config["tier1"]
    tier1_count = int((tier1["tau_max"] - tier1["tau_min"]) / tier1["tau_step"]) + 1
    assert tier0_count == 7
    assert tier1_count == 21
