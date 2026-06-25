from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from rdflib import RDF, RDFS

from .benchmark_profiles import BuiltProfileRecord, CRM, EX


@dataclass(frozen=True)
class QueryEvaluation:
    answers: frozenset[str]
    runtime_ms: float
    execution_engine: str = "rdflib_graph_api"


def _timed(function: Callable[[], set[str]]) -> QueryEvaluation:
    started = time.perf_counter()
    answers = function()
    return QueryEvaluation(
        answers=frozenset(answers),
        runtime_ms=(time.perf_counter() - started) * 1000,
    )


def _label(graph, node) -> str:
    return str(next(graph.objects(node, RDFS.label), node))

def _canonical_event_id(graph, node) -> str:
    return str(next(graph.objects(node, EX.canonicalEventId), node))


def evaluate_query(
    family: str, built: BuiltProfileRecord
) -> QueryEvaluation:
    graph = built.graph

    def direct_maker() -> set[str]:
        return {
            _label(graph, maker)
            for production in graph.subjects(CRM.P108_has_produced, built.current)
            for maker in graph.objects(production, CRM.P14_carried_out_by)
        }

    def lineage_maker() -> set[str]:
        originals = {
            original
            for production in graph.subjects(RDF.type, CRM.E12_Production)
            for original in graph.objects(production, CRM.P108_has_produced)
        }
        reached = set(originals)
        frontier = set(originals)
        while frontier:
            next_frontier = {
                newer
                for old in frontier
                for transformation in graph.subjects(CRM.P124_transformed, old)
                for newer in graph.objects(transformation, CRM.P123_resulted_in)
            } - reached
            reached.update(next_frontier)
            frontier = next_frontier
        if built.current not in reached:
            return set()
        return {
            _label(graph, maker)
            for production in graph.subjects(RDF.type, CRM.E12_Production)
            for maker in graph.objects(production, CRM.P14_carried_out_by)
        }

    def e13_maker() -> set[str]:
        answers = set()
        for assignment in graph.subjects(
            RDF.type, CRM.E13_Attribute_Assignment
        ):
            if (
                assignment,
                CRM.P177_assigned_property_of_type,
                CRM.P14_carried_out_by,
            ) not in graph:
                continue
            for production in graph.objects(
                assignment, CRM.P140_assigned_attribute_to
            ):
                originals = set(
                    graph.objects(production, CRM.P108_has_produced)
                )
                reached = set(originals)
                frontier = set(originals)
                while frontier:
                    next_frontier = {
                        newer
                        for old in frontier
                        for transformation in graph.subjects(
                            CRM.P124_transformed, old
                        )
                        for newer in graph.objects(
                            transformation, CRM.P123_resulted_in
                        )
                    } - reached
                    reached.update(next_frontier)
                    frontier = next_frontier
                if built.current in reached:
                    answers.update(
                        _label(graph, maker)
                        for maker in graph.objects(
                            assignment, CRM.P141_assigned
                        )
                    )
        return answers

    def classification() -> set[str]:
        return {
            _label(graph, node)
            for node in graph.objects(built.current, CRM.P2_has_type)
        }

    def lineage_classification() -> set[str]:
        return {
            _label(graph, node)
            for object_node in built.objects
            for node in graph.objects(object_node, CRM.P2_has_type)
        }

    def material_component() -> set[str]:
        return {
            _label(graph, node)
            for predicate in (CRM.P45_consists_of, CRM.P46_is_composed_of)
            for node in graph.objects(built.current, predicate)
        }

    def lineage_material_component() -> set[str]:
        return {
            _label(graph, node)
            for object_node in built.objects
            for predicate in (CRM.P45_consists_of, CRM.P46_is_composed_of)
            for node in graph.objects(object_node, predicate)
        }

    def modification_history() -> set[str]:
        return {
            _canonical_event_id(graph, event)
            for event in built.event_nodes
            if any(
                any(graph.objects(event, predicate))
                for predicate in (
                    CRM.P31_has_modified,
                    CRM.P110_augmented,
                    CRM.P112_diminished,
                )
            )
        }

    def current_modification_history() -> set[str]:
        return {
            _canonical_event_id(graph, event)
            for event in built.event_nodes
            if any(
                built.current in set(graph.objects(event, predicate))
                for predicate in (
                    CRM.P31_has_modified,
                    CRM.P110_augmented,
                    CRM.P112_diminished,
                )
            )
        }

    def part_history() -> set[str]:
        return {
            _canonical_event_id(graph, event)
            for event in built.event_nodes
            if (event, RDF.type, CRM.E79_Part_Addition) in graph
            or (event, RDF.type, CRM.E80_Part_Removal) in graph
        }

    def current_part_history() -> set[str]:
        return {
            _canonical_event_id(graph, event)
            for event in built.event_nodes
            if (
                built.current in set(graph.objects(event, CRM.P110_augmented))
                or built.current
                in set(graph.objects(event, CRM.P112_diminished))
            )
        }

    def condition_history() -> set[str]:
        return {
            _label(graph, condition)
            for object_node in built.objects
            for condition in graph.objects(object_node, CRM.P44_has_condition)
        }

    def current_condition_history() -> set[str]:
        return {
            _label(graph, condition)
            for condition in graph.objects(built.current, CRM.P44_has_condition)
        }

    def attribution_classification_history() -> set[str]:
        return {
            _canonical_event_id(graph, event)
            for event in built.event_nodes
            for kind in graph.objects(event, EX.eventKind)
            if str(kind) in {"attribution_change", "classification_change"}
        }

    def current_attribution_classification_history() -> set[str]:
        return {
            _canonical_event_id(graph, event)
            for event in built.event_nodes
            if built.current
            in set(graph.objects(event, CRM.P140_assigned_attribute_to))
            for kind in graph.objects(event, EX.eventKind)
            if str(kind) in {"attribution_change", "classification_change"}
        }

    evaluators = {
        "maker_direct": direct_maker,
        "maker_lineage": lineage_maker,
        "maker_e13": e13_maker,
        "classification_current": classification,
        "classification_lineage": lineage_classification,
        "material_component_current": material_component,
        "material_component_lineage": lineage_material_component,
        "modification_history": modification_history,
        "modification_current_segment": current_modification_history,
        "modification_lineage": modification_history,
        "part_history": part_history,
        "part_current_segment": current_part_history,
        "part_lineage": part_history,
        "condition_history": condition_history,
        "condition_current_segment": current_condition_history,
        "condition_lineage": condition_history,
        "attribution_classification_history": attribution_classification_history,
        "attribution_classification_current_segment": current_attribution_classification_history,
        "attribution_classification_lineage": attribution_classification_history,
    }
    if family not in evaluators:
        raise ValueError(f"unknown benchmark query family: {family}")
    return _timed(evaluators[family])
