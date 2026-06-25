from __future__ import annotations

from dataclasses import dataclass

from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import XSD

from .extraction import Record, slug
from .segmentation import Segment

CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
EX = Namespace("http://example.org/remake/")


@dataclass(frozen=True)
class BuiltRecord:
    graph: Graph
    record_id: str
    original: URIRef
    current: URIRef
    segments: tuple[URIRef, ...]
    maker: URIRef | None


def build_record_graph(
    record: Record,
    segments: list[Segment],
    *,
    authoring_convention: str = "strict_production",
) -> BuiltRecord:
    if authoring_convention not in {
        "strict_production",
        "propagated_production",
        "separate_lineage_maker",
    }:
        raise ValueError(f"unknown authoring convention: {authoring_convention}")
    graph = Graph()
    graph.bind("crm", CRM)
    graph.bind("ex", EX)
    segment_nodes = tuple(
        EX[f"{record.record_id}_obj_{segment.index:03d}"] for segment in segments
    )
    if not segment_nodes:
        raise ValueError(f"{record.record_id} has no segments")

    for node in segment_nodes:
        graph.add((node, RDF.type, CRM.E22_Human_Made_Object))
    original = segment_nodes[0]
    current = segment_nodes[-1]
    graph.add((current, EX.isCurrent, Literal(True, datatype=XSD.boolean)))

    maker_node = EX[f"agent_{slug(record.maker)}"] if record.maker else None
    production = EX[f"{record.record_id}_production"]
    graph.add((production, RDF.type, CRM.E12_Production))
    graph.add((production, CRM.P108_has_produced, original))
    if maker_node is not None:
        graph.add((maker_node, RDF.type, CRM.E21_Person))
        graph.add((maker_node, RDF.type, CRM.E39_Actor))
        graph.add((production, CRM.P14_carried_out_by, maker_node))
        if authoring_convention == "propagated_production":
            for segment_node in segment_nodes[1:]:
                graph.add((production, CRM.P108_has_produced, segment_node))
        elif authoring_convention == "separate_lineage_maker":
            for segment_node in segment_nodes:
                graph.add((segment_node, EX.hasLineageMaker, maker_node))

    for segment, segment_node in zip(segments, segment_nodes):
        for event in segment.events:
            event_node = EX[event.event_id]
            graph.add((event_node, RDF.type, CRM.E11_Modification))
            graph.add((event_node, CRM.P31_has_modified, segment_node))
            graph.add((event_node, EX.eventLabel, Literal(event.label)))
            for element in event.elements:
                graph.add((event_node, EX.affectsElement, Literal(element)))

    for index, (old, new) in enumerate(zip(segment_nodes, segment_nodes[1:]), start=1):
        trans = EX[f"{record.record_id}_trans_{index:03d}_{index + 1:03d}"]
        graph.add((trans, RDF.type, CRM.E81_Transformation))
        graph.add((trans, CRM.P124_transformed, old))
        graph.add((trans, CRM.P123_resulted_in, new))
        graph.add((old, EX.precedesSegment, new))
        graph.add((new, EX.followsSegment, old))

    return BuiltRecord(
        graph=graph,
        record_id=record.record_id,
        original=original,
        current=current,
        segments=segment_nodes,
        maker=maker_node,
    )


def validate_segment_chain(graph: Graph, record_id: str) -> list[str]:
    errors: list[str] = []
    production = EX[f"{record_id}_production"]
    originals = list(graph.objects(production, CRM.P108_has_produced))
    currents = list(graph.subjects(EX.isCurrent, Literal(True, datatype=XSD.boolean)))
    currents = [node for node in currents if str(node).startswith(str(EX[record_id]))]
    segments = sorted(
        {
            node
            for node in graph.subjects(RDF.type, CRM.E22_Human_Made_Object)
            if str(node).startswith(str(EX[f"{record_id}_obj_"]))
        },
        key=str,
    )
    edges = [
        (old, new)
        for old, new in graph.subject_objects(EX.precedesSegment)
        if old in segments and new in segments
    ]
    if len(originals) != 1:
        errors.append(f"expected exactly one produced/original segment; found {len(originals)}")
    if len(currents) != 1:
        errors.append(f"expected exactly one current segment; found {len(currents)}")
    if len(edges) != max(0, len(segments) - 1):
        errors.append(
            f"expected {max(0, len(segments) - 1)} precedesSegment edges; found {len(edges)}"
        )
    if originals and currents:
        frontier = {originals[0]}
        reached = set(frontier)
        while frontier:
            frontier = {
                nxt
                for node in frontier
                for nxt in graph.objects(node, EX.precedesSegment)
                if nxt not in reached
            }
            reached.update(frontier)
        if currents[0] not in reached:
            errors.append("original segment does not reach current through precedesSegment*")
        if len(segments) == 1 and originals[0] != currents[0]:
            errors.append("single segment is not both original and current")
    return errors
