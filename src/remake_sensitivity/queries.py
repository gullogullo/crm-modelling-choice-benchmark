from __future__ import annotations

import networkx as nx

from rdflib import RDF

from .graph import BuiltRecord, CRM, EX

Q1_SPARQL = """
PREFIX ex: <http://example.org/remake/>
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>

SELECT DISTINCT ?current WHERE {
  ?prod a crm:E12_Production ;
        crm:P14_carried_out_by ?maker ;
        crm:P108_has_produced ?current .

  ?current ex:isCurrent true .
}
"""

Q2_SPARQL = """
PREFIX ex: <http://example.org/remake/>
PREFIX crm: <http://www.cidoc-crm.org/cidoc-crm/>

SELECT DISTINCT ?current WHERE {
  ?prod a crm:E12_Production ;
        crm:P14_carried_out_by ?maker ;
        crm:P108_has_produced ?original .

  ?original ex:precedesSegment* ?current .

  ?current ex:isCurrent true .
}
"""


def q1_current_direct_zero_hop_by_maker(built: BuiltRecord) -> bool:
    if built.maker is None:
        return False
    graph = built.graph
    return any(
        (production, CRM.P108_has_produced, built.current) in graph
        for production in graph.subjects(CRM.P14_carried_out_by, built.maker)
        if (production, RDF.type, CRM.E12_Production) in graph
    )


def q2_current_reachable_zero_or_more_by_maker(built: BuiltRecord) -> bool:
    if built.maker is None:
        return False
    graph = built.graph
    originals = [
        original
        for production in graph.subjects(CRM.P14_carried_out_by, built.maker)
        for original in graph.objects(production, CRM.P108_has_produced)
    ]
    if built.current in originals:
        return True
    lineage = nx.DiGraph(graph.subject_objects(EX.precedesSegment))
    return any(
        original in lineage
        and built.current in lineage
        and nx.has_path(lineage, original, built.current)
        for original in originals
    )


def q2_current_reachable_native_crm(built: BuiltRecord) -> bool:
    if built.maker is None:
        return False
    graph = built.graph
    originals = [
        original
        for production in graph.subjects(CRM.P14_carried_out_by, built.maker)
        for original in graph.objects(production, CRM.P108_has_produced)
    ]
    frontier = set(originals)
    reached = set(frontier)
    while frontier:
        next_frontier = set()
        for old in frontier:
            for transformation in graph.subjects(CRM.P124_transformed, old):
                next_frontier.update(
                    graph.objects(transformation, CRM.P123_resulted_in)
                )
        next_frontier -= reached
        reached.update(next_frontier)
        frontier = next_frontier
    return built.current in reached


def q3_transformation_depth_to_current(built: BuiltRecord) -> int | None:
    if built.original == built.current:
        return 0
    lineage = nx.DiGraph(built.graph.subject_objects(EX.precedesSegment))
    try:
        return nx.shortest_path_length(lineage, built.original, built.current)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None


def q4_current_same_as_original_segment(built: BuiltRecord) -> bool:
    return built.current == built.original


def q5_direct_vs_reachable_gap(built: BuiltRecord) -> int:
    return int(q2_current_reachable_zero_or_more_by_maker(built)) - int(
        q1_current_direct_zero_hop_by_maker(built)
    )


def current_has_lineage_maker(built: BuiltRecord) -> bool:
    return built.maker is not None and (
        built.current, EX.hasLineageMaker, built.maker
    ) in built.graph


QUERY_AUDIT = (
    (
        "Q1",
        "current_direct_zero_hop_by_maker",
        "hop_sensitive",
        "variable",
        "current object may cease to be the original produced segment",
    ),
    (
        "Q2",
        "current_reachable_zero_or_more_by_maker",
        "hop_invariant_negative_control",
        "flat",
        "zero-or-more path preserves reachability from produced segment to current segment",
    ),
    (
        "Q3",
        "transformation_depth_to_current",
        "topological_statistic",
        "variable",
        "fragmentation increases number of segment hops",
    ),
    (
        "Q4",
        "current_same_as_original_segment",
        "hop_sensitive",
        "variable",
        "true only when current segment is the produced segment",
    ),
    (
        "Q5",
        "direct_vs_reachable_gap",
        "hop_sensitive",
        "variable",
        "gap grows when direct attribution diverges from reachable lineage",
    ),
)
