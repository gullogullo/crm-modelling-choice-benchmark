from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import XSD

from .canonical_events import CanonicalEvent, CanonicalRecord
from .extraction import slug
from .segmentation import Event, Segment, segment_tier0, segment_tier1

CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
EX = Namespace("http://example.org/remake/")


@dataclass(frozen=True)
class BenchmarkSetting:
    tier: str
    parameter_name: str
    parameter_value: str
    scenario_config: dict[str, Any] | None = None

    @property
    def setting_id(self) -> str:
        return (
            f"{self.tier}_{self.parameter_name}_"
            f"{self.parameter_value.replace('.', '_')}"
        )


@dataclass(frozen=True)
class BuiltProfileRecord:
    graph: Graph
    profile_id: str
    setting: BenchmarkSetting
    record_id: str
    original: URIRef
    current: URIRef
    objects: tuple[URIRef, ...]
    maker: URIRef | None
    event_nodes: tuple[URIRef, ...]


def configured_settings(config: dict[str, Any]) -> list[BenchmarkSetting]:
    maximum = config["tier0"]["k_max"]
    if maximum is None:
        maximum = max(
            1,
            max(
                (int(value) for value in config.get("_record_event_counts", [1])),
                default=1,
            ),
        )
    settings = [
        BenchmarkSetting("tier0", "k", str(value))
        for value in range(config["tier0"]["k_min"], maximum + 1)
    ]
    current = config["tier1"]["tau_min"]
    while current <= config["tier1"]["tau_max"] + 1e-9:
        settings.append(BenchmarkSetting("tier1", "tau", f"{current:.2f}"))
        current = round(current + config["tier1"]["tau_step"], 10)
    settings.extend(
        BenchmarkSetting(
            "scenario",
            "scenario",
            scenario_id,
            scenario_config=scenario,
        )
        for scenario_id, scenario in config.get(
            "_segmentation_scenarios", {}
        ).items()
    )
    return settings


def _segments_from_boundaries(
    events: list[Event], boundary_positions: set[int]
) -> list[Segment]:
    segments = []
    current = []
    for position, event in enumerate(events, start=1):
        current.append(event)
        if position in boundary_positions and position < len(events):
            segments.append(Segment(index=len(segments) + 1, events=tuple(current)))
            current = []
    if current:
        segments.append(Segment(index=len(segments) + 1, events=tuple(current)))
    return segments


def segments_for_record(
    record: CanonicalRecord,
    setting: BenchmarkSetting,
    *,
    persistent: bool = False,
) -> list[Segment]:
    events = [event.as_segment_event() for event in record.events]
    if persistent:
        return [Segment(index=1, events=tuple(events))]
    if setting.tier == "tier0":
        return segment_tier0(events, int(float(setting.parameter_value)))
    if setting.tier == "scenario":
        scenario = setting.scenario_config or {}
        strategy = scenario["strategy"]
        if strategy == "no_replacement":
            return [Segment(index=1, events=tuple(events))]
        if strategy == "event_kind_boundaries":
            kinds = set(scenario.get("boundary_event_kinds", []))
            positions = {
                position
                for position, event in enumerate(record.events, start=1)
                if event.event_kind in kinds
            }
            return _segments_from_boundaries(events, positions)
        if strategy == "explicit_replacement_only":
            terms = tuple(term.lower() for term in scenario.get("boundary_terms", []))
            positions = {
                position
                for position, event in enumerate(record.events, start=1)
                if any(
                    term in f"{event.event_label} {event.event_description}".lower()
                    for term in terms
                )
            }
            return _segments_from_boundaries(events, positions)
        if strategy == "manual_boundaries":
            positions = set(
                scenario.get("boundaries_by_record", {}).get(record.record_id, [])
            )
            return _segments_from_boundaries(events, positions)
        raise ValueError(f"unknown segmentation scenario strategy: {strategy}")
    if record.total_elements == 0:
        return []
    return segment_tier1(
        events,
        float(setting.parameter_value),
        total_elements=record.total_elements,
    )


def _node(profile_id: str, record_id: str, suffix: str) -> URIRef:
    return EX[f"{profile_id}_{record_id}_{suffix}"]


def _add_descriptive_data(
    graph: Graph,
    record: CanonicalRecord,
    current: URIRef,
) -> None:
    source = _node("state", record.record_id, "catalogue_source")
    graph.add((source, RDF.type, CRM.E73_Information_Object))
    graph.add((source, RDFS.label, Literal(" | ".join(record.source_references) or record.record_id)))
    for index, classification in enumerate(record.classifications, start=1):
        node = EX[f"type_{slug(classification)}"]
        graph.add((node, RDF.type, CRM.E55_Type))
        graph.add((node, RDFS.label, Literal(classification)))
        graph.add((current, CRM.P2_has_type, node))
        assignment = _node("state", record.record_id, f"classification_{index:03d}")
        graph.add((assignment, RDF.type, CRM.E13_Attribute_Assignment))
        graph.add((assignment, CRM.P140_assigned_attribute_to, current))
        graph.add((assignment, CRM.P141_assigned, node))
        graph.add((assignment, CRM.P177_assigned_property_of_type, CRM.P2_has_type))
        graph.add((assignment, CRM.P16_used_specific_object, source))
        graph.add((assignment, EX.assertionScope, Literal("current_catalogue_state")))
    for index, material in enumerate(record.materials, start=1):
        node = EX[f"material_{slug(material)}"]
        graph.add((node, RDF.type, CRM.E57_Material))
        graph.add((node, RDFS.label, Literal(material)))
        graph.add((current, CRM.P45_consists_of, node))
        assignment = _node("state", record.record_id, f"material_{index:03d}")
        graph.add((assignment, RDF.type, CRM.E13_Attribute_Assignment))
        graph.add((assignment, CRM.P140_assigned_attribute_to, current))
        graph.add((assignment, CRM.P141_assigned, node))
        graph.add((assignment, CRM.P177_assigned_property_of_type, CRM.P45_consists_of))
        graph.add((assignment, CRM.P16_used_specific_object, source))
        graph.add((assignment, EX.assertionScope, Literal("current_catalogue_state")))
    for component in record.components:
        node = EX[f"component_{slug(component)}"]
        graph.add((node, RDF.type, CRM.E18_Physical_Thing))
        graph.add((node, RDFS.label, Literal(component)))
        graph.add((current, CRM.P46_is_composed_of, node))


def _event_target_map(
    segments: list[Segment], object_nodes: tuple[URIRef, ...]
) -> dict[str, URIRef]:
    return {
        event.event_id: object_node
        for segment, object_node in zip(segments, object_nodes)
        for event in segment.events
    }


def _add_event(
    graph: Graph,
    profile_id: str,
    event: CanonicalEvent,
    target: URIRef,
) -> URIRef:
    event_node = _node(profile_id, event.record_id, event.event_id)
    if event.event_kind == "creation":
        event_class = CRM.E12_Production
        relation = CRM.P108_has_produced
    elif event.event_kind == "part_addition":
        event_class = CRM.E79_Part_Addition
        relation = CRM.P110_augmented
    elif event.event_kind == "part_removal":
        event_class = CRM.E80_Part_Removal
        relation = CRM.P112_diminished
    elif event.event_kind in {"attribution_change", "classification_change"}:
        event_class = CRM.E13_Attribute_Assignment
        relation = CRM.P140_assigned_attribute_to
    else:
        event_class = CRM.E11_Modification
        relation = CRM.P31_has_modified
    graph.add((event_node, RDF.type, event_class))
    graph.add((event_node, relation, target))
    graph.add((event_node, EX.canonicalEventId, Literal(event.event_id)))
    graph.add((event_node, EX.eventKind, Literal(event.event_kind)))
    graph.add((event_node, EX.eventLabel, Literal(event.event_label)))
    graph.add((event_node, EX.sourceOrder, Literal(event.source_order)))
    graph.add((event_node, EX.validAtEvent, event_node))
    if (
        event.event_kind in {"attribution_change", "classification_change"}
        and event.agent
        and event.agent.upper() != "UNKNOWN"
    ):
        responsible = EX[f"agent_{slug(event.agent)}"]
        graph.add((responsible, RDF.type, CRM.E39_Actor))
        graph.add((responsible, RDFS.label, Literal(event.agent)))
        graph.add((event_node, CRM.P14_carried_out_by, responsible))
    if event.parsed_date_interval:
        graph.add((event_node, EX.parsedDateInterval, Literal(event.parsed_date_interval)))
    if event.source_reference:
        graph.add((event_node, EX.sourceReference, Literal(event.source_reference)))
    for label in event.affected_component_labels:
        graph.add((event_node, EX.affectsComponentLabel, Literal(label)))
    if event.event_kind == "condition":
        condition = _node(profile_id, event.record_id, f"{event.event_id}_condition")
        graph.add((condition, RDF.type, CRM.E3_Condition_State))
        graph.add((condition, RDFS.label, Literal(event.event_description)))
        graph.add((target, CRM.P44_has_condition, condition))
    return event_node


def build_profile_record(
    profile_id: str,
    profile_config: dict[str, Any],
    record: CanonicalRecord,
    setting: BenchmarkSetting,
) -> BuiltProfileRecord | None:
    builder = profile_config["builder"]
    persistent = builder == "persistent_e11"
    segments = segments_for_record(record, setting, persistent=persistent)
    if not segments:
        return None
    graph = Graph()
    graph.bind("crm", CRM)
    graph.bind("ex", EX)
    graph.bind("rdfs", RDFS)
    objects = tuple(
        _node(profile_id, record.record_id, f"obj_{index:03d}")
        for index in range(1, len(segments) + 1)
    )
    for object_node in objects:
        graph.add((object_node, RDF.type, CRM.E22_Human_Made_Object))
        graph.add((object_node, EX.sourceRecordId, Literal(record.record_id)))
    original, current = objects[0], objects[-1]
    graph.add((current, EX.isCurrent, Literal(True, datatype=XSD.boolean)))
    production = _node(profile_id, record.record_id, "production")
    graph.add((production, RDF.type, CRM.E12_Production))
    graph.add((production, CRM.P108_has_produced, original))
    maker = EX[f"agent_{slug(record.maker)}"] if record.maker else None
    if maker is not None:
        graph.add((maker, RDF.type, CRM.E39_Actor))
        graph.add((maker, RDFS.label, Literal(record.maker)))
        graph.add((production, CRM.P14_carried_out_by, maker))
    if builder == "segmented_e81_propagated_p108":
        for object_node in objects[1:]:
            graph.add((production, CRM.P108_has_produced, object_node))
    targets = _event_target_map(segments, objects)
    event_nodes = tuple(
        _add_event(graph, profile_id, event, targets[event.event_id])
        for event in record.events
    )
    for index, (old, new) in enumerate(zip(objects, objects[1:]), start=1):
        transformation = _node(
            profile_id, record.record_id, f"trans_{index:03d}_{index+1:03d}"
        )
        graph.add((transformation, RDF.type, CRM.E81_Transformation))
        graph.add((transformation, CRM.P124_transformed, old))
        graph.add((transformation, CRM.P123_resulted_in, new))
        graph.add((old, EX.precedesSegment, new))
    if builder == "segmented_e81_e13" and maker is not None:
        assignment = _node(profile_id, record.record_id, "maker_assignment")
        source = _node(profile_id, record.record_id, "source_documentation")
        method = EX.crmNativeLineageDerivation
        graph.add((assignment, RDF.type, CRM.E13_Attribute_Assignment))
        graph.add((assignment, CRM.P140_assigned_attribute_to, production))
        graph.add((assignment, CRM.P141_assigned, maker))
        graph.add(
            (
                assignment,
                CRM.P177_assigned_property_of_type,
                CRM.P14_carried_out_by,
            )
        )
        graph.add((assignment, CRM.P16_used_specific_object, source))
        graph.add((assignment, CRM.P33_used_specific_technique, method))
        graph.add((assignment, EX.sourceReference, source))
        graph.add((assignment, EX.derivationMethod, method))
        for responsible_label in record.attribution_responsibility:
            responsible = EX[f"agent_{slug(responsible_label)}"]
            graph.add((responsible, RDF.type, CRM.E39_Actor))
            graph.add((responsible, RDFS.label, Literal(responsible_label)))
            graph.add((assignment, CRM.P14_carried_out_by, responsible))
        graph.add((CRM.P14_carried_out_by, RDF.type, CRM.E55_Type))
        graph.add(
            (
                CRM.P14_carried_out_by,
                RDFS.label,
                Literal("P14 carried out by"),
            )
        )
        graph.add((source, RDF.type, CRM.E73_Information_Object))
        graph.add(
            (
                source,
                RDFS.label,
                Literal(" | ".join(record.source_references) or record.record_id),
            )
        )
        graph.add((method, RDF.type, CRM.E29_Design_or_Procedure))
        graph.add(
            (
                method,
                RDFS.label,
                Literal("Derived from strict production plus CRM E81 lineage"),
            )
        )
    _add_descriptive_data(graph, record, current)
    return BuiltProfileRecord(
        graph=graph,
        profile_id=profile_id,
        setting=setting,
        record_id=record.record_id,
        original=original,
        current=current,
        objects=objects,
        maker=maker,
        event_nodes=event_nodes,
    )


def serialize_profile_graph(
    path: Path, built_records: list[BuiltProfileRecord]
) -> None:
    graph = Graph()
    graph.bind("crm", CRM)
    graph.bind("ex", EX)
    graph.bind("rdfs", RDFS)
    for built in built_records:
        graph += built.graph
    path.parent.mkdir(parents=True, exist_ok=True)
    graph.serialize(path, format="turtle")
