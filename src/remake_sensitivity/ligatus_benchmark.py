from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml
from rdflib import Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import XSD

from .ligatus_adapter import (
    LigatusRecord,
    load_ordering_manifest,
    load_records,
    write_canonical_table,
)


CRM = Namespace("http://www.cidoc-crm.org/cidoc-crm/")
EX = Namespace("http://example.org/remake/ligatus/")


@dataclass(frozen=True)
class BuiltLigatusRecord:
    profile_id: str
    record: LigatusRecord
    graph: Graph
    identities: tuple[URIRef, ...]
    current: URIRef
    root_identity: dict[str, URIRef]


def _node(profile: str, record_id: str, suffix: str) -> URIRef:
    safe = "".join(character if character.isalnum() else "_" for character in record_id)
    return EX[f"{profile}_{safe}_{suffix}"]


def build_profile(record: LigatusRecord, profile_id: str) -> BuiltLigatusRecord:
    graph = Graph()
    graph += record.graph
    graph.bind("crm", CRM)
    graph.bind("ex", EX)
    episodes = record.episode_ids
    if profile_id == "persistent_e11":
        identities = (URIRef(record.object_id),)
        root_identity = {episode: identities[0] for episode in episodes}
    elif profile_id == "segmented_e81":
        identities = tuple(
            _node(profile_id, record.record_id, f"identity_{index:03d}")
            for index in range(len(episodes) + 1)
        )
        for identity in identities:
            graph.add((identity, RDF.type, CRM.E22_Man_Made_Object))
            graph.add((identity, EX.sourceObject, URIRef(record.object_id)))
        root_identity = {
            episode: identities[index]
            for index, episode in enumerate(episodes, start=1)
        }
        for index, episode in enumerate(episodes, start=1):
            transformation = _node(
                profile_id, record.record_id, f"transformation_{index:03d}"
            )
            graph.add((transformation, RDF.type, CRM.E81_Transformation))
            graph.add((transformation, CRM.P124_transformed, identities[index - 1]))
            graph.add((transformation, CRM.P123_resulted_in, identities[index]))
            graph.add(
                (
                    transformation,
                    EX.realizedByTreatmentEpisode,
                    URIRef(episode),
                )
            )
    else:
        raise ValueError(f"unknown Ligatus profile: {profile_id}")
    current = identities[-1]
    graph.add((current, EX.isCurrent, Literal(True, datatype=XSD.boolean)))
    for event in record.events:
        identity = root_identity[event.episode_id]
        event_node = URIRef(event.event_id)
        graph.add((event_node, EX.appliesToIdentity, identity))
        graph.add(
            (event_node, EX.treatmentEpisode, URIRef(event.episode_id))
        )
        graph.add(
            (event_node, EX.episodeOrder, Literal(event.episode_order))
        )
        graph.add(
            (
                event_node,
                EX.episodeOrderBasis,
                Literal(event.episode_order_basis),
            )
        )
        graph.add((event_node, EX.hierarchyDepth, Literal(event.hierarchy_depth)))
        if event.root_begin:
            graph.add((event_node, EX.rootBegin, Literal(event.root_begin)))
        if event.root_end:
            graph.add((event_node, EX.rootEnd, Literal(event.root_end)))
    return BuiltLigatusRecord(
        profile_id=profile_id,
        record=record,
        graph=graph,
        identities=identities,
        current=current,
        root_identity=root_identity,
    )


def _label(graph: Graph, node) -> str:
    return str(next(graph.objects(node, RDFS.label), node))


def _events_for_identities(
    built: BuiltLigatusRecord, identities: set[URIRef]
) -> set[URIRef]:
    return {
        event
        for identity in identities
        for event in built.graph.subjects(EX.appliesToIdentity, identity)
    }


def _lineage_identities(built: BuiltLigatusRecord) -> set[URIRef]:
    return set(built.identities)


def evaluate_query(
    built: BuiltLigatusRecord, query_id: str
) -> tuple[set[str], float]:
    graph = built.graph
    current_events = _events_for_identities(built, {built.current})
    lineage_events = _events_for_identities(built, _lineage_identities(built))
    event_by_id = {event.event_id: event for event in built.record.events}

    def treatment_history(events: set[URIRef]) -> set[str]:
        return {
            event_by_id[str(event)].episode_id
            for event in events
        }

    def modifications(events: set[URIRef]) -> set[str]:
        return {str(event) for event in events}

    def condition_treatment(events: set[URIRef]) -> set[str]:
        answers = set()
        for event in events:
            for target in graph.subjects(CRM.P31i_was_modified_by, event):
                for condition in graph.objects(target, CRM.P44_has_condition):
                    answers.add(f"{event}|{_label(graph, condition)}")
        return answers

    def values_over_time(events: set[URIRef], predicate) -> set[str]:
        answers = set()
        for event in events:
            canonical = event_by_id[str(event)]
            for value in graph.objects(event, predicate):
                date = canonical.root_begin or canonical.root_end or "undated"
                answers.add(
                    f"{canonical.episode_order}:{date}|{event}|{_label(graph, value)}"
                )
        return answers

    evaluators: dict[str, Callable[[], set[str]]] = {
        "current_treatment_history": lambda: treatment_history(current_events),
        "lineage_treatment_history": lambda: treatment_history(lineage_events),
        "current_modification_retrieval": lambda: modifications(current_events),
        "lineage_modification_retrieval": lambda: modifications(lineage_events),
        "current_condition_to_treatment": lambda: condition_treatment(current_events),
        "lineage_condition_to_treatment": lambda: condition_treatment(lineage_events),
        "current_treatment_material_over_time": lambda: values_over_time(
            current_events, CRM.P126_employed
        ),
        "lineage_treatment_material_over_time": lambda: values_over_time(
            lineage_events, CRM.P126_employed
        ),
        "current_technique_over_time": lambda: values_over_time(
            current_events, CRM.P32_used_general_technique
        ),
        "lineage_technique_over_time": lambda: values_over_time(
            lineage_events, CRM.P32_used_general_technique
        ),
    }
    started = time.perf_counter()
    answers = evaluators[query_id]()
    return answers, (time.perf_counter() - started) * 1000


QUERY_LABELS = {
    "current_treatment_history": "Which top-level treatment episodes are local to the current identity?",
    "lineage_treatment_history": "Which top-level treatment episodes occur anywhere in the current identity's lineage?",
    "current_modification_retrieval": "Which E11 modifications are local to the current identity?",
    "lineage_modification_retrieval": "Which E11 modifications occur anywhere in the current identity's lineage?",
    "current_condition_to_treatment": "Which condition states are associated through treated components with current-local modifications?",
    "lineage_condition_to_treatment": "Which condition states are associated through treated components with lineage-wide modifications?",
    "current_treatment_material_over_time": "Which treatment materials occur in current-local modifications, with supplied episode order/date?",
    "lineage_treatment_material_over_time": "Which treatment materials occur over the full treatment lineage?",
    "current_technique_over_time": "Which treatment techniques occur in current-local modifications, with supplied episode order/date?",
    "lineage_technique_over_time": "Which treatment techniques occur over the full treatment lineage?",
}

LOCAL_LINEAGE_PAIRS = (
    ("current_treatment_history", "lineage_treatment_history"),
    ("current_modification_retrieval", "lineage_modification_retrieval"),
    ("current_condition_to_treatment", "lineage_condition_to_treatment"),
    (
        "current_treatment_material_over_time",
        "lineage_treatment_material_over_time",
    ),
    ("current_technique_over_time", "lineage_technique_over_time"),
)

PROPERTY_QUERY_PAIRS = (
    (
        "condition",
        "current_condition_to_treatment",
        "lineage_condition_to_treatment",
    ),
    (
        "treatment_material",
        "current_treatment_material_over_time",
        "lineage_treatment_material_over_time",
    ),
    ("technique", "current_technique_over_time", "lineage_technique_over_time"),
)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _answer_map(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], set[str]]:
    return {
        (row["profile_id"], row["record_id"], row["query_id"]): set(
            filter(None, str(row["answer_values"]).split(" || "))
        )
        for row in rows
    }


def _normal_root_label(label: str) -> str:
    return label.split("(", 1)[0].strip().lower()


def _join_audit_values(values) -> str:
    return " || ".join(str(value) if str(value) else "<none>" for value in values)


def _ordering_basis(rule_id: str) -> str:
    if rule_id == "parsed_dates":
        return "date"
    if rule_id == "previous_repair_before_main_event":
        return "label"
    if rule_id == "all_roots_split":
        return "URI"
    if rule_id == "no_supported_order":
        return "collapsed"
    return rule_id


def _event_uri_from_answer(answer: str) -> str:
    parts = answer.split("|")
    if len(parts) >= 3:
        return parts[1]
    return parts[0]


def _event_lookup(record: LigatusRecord) -> dict[str, Any]:
    return {event.event_id: event for event in record.events}


def _root_label_map(record: LigatusRecord) -> dict[str, str]:
    return dict(zip(record.source_root_ids, record.source_root_labels))


def _implemented_path_counts(record: LigatusRecord, root_ids: set[str]) -> dict[str, int]:
    graph = record.graph
    counts = Counter()
    for event in record.events:
        if event.root_event_id not in root_ids:
            continue
        event_node = URIRef(event.event_id)
        counts["P126"] += sum(1 for _ in graph.objects(event_node, CRM.P126_employed))
        counts["P32"] += sum(
            1 for _ in graph.objects(event_node, CRM.P32_used_general_technique)
        )
        for target in graph.subjects(CRM.P31i_was_modified_by, event_node):
            counts["P44"] += sum(1 for _ in graph.objects(target, CRM.P44_has_condition))
    return dict(counts)


def _root_label_inventory(records: list[LigatusRecord]) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]]
]:
    label_counts = Counter()
    label_one_root_counts = Counter()
    label_two_root_counts = Counter()
    pattern_counts = Counter()
    pattern_examples: dict[tuple[str, ...], list[str]] = {}
    pattern_actions: dict[tuple[str, ...], Counter] = {}

    for record in records:
        labels = tuple(_normal_root_label(label) for label in record.source_root_labels)
        for label in labels:
            label_counts[label] += 1
            if record.source_root_count == 1:
                label_one_root_counts[label] += 1
            elif record.source_root_count == 2:
                label_two_root_counts[label] += 1
        if record.source_root_count == 2:
            pattern_counts[labels] += 1
            pattern_examples.setdefault(labels, []).append(record.record_id)
            pattern_actions.setdefault(labels, Counter())[record.ordering_rule_id] += 1

    label_rows = [
        {
            "root_label_normalized": label,
            "root_count": label_counts[label],
            "one_root_count": label_one_root_counts[label],
            "two_root_count": label_two_root_counts[label],
        }
        for label in sorted(label_counts)
    ]
    pattern_rows = []
    for labels, count in sorted(
        pattern_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        actions = pattern_actions[labels]
        pattern_rows.append(
            {
                "root_label_pattern": " || ".join(labels),
                "record_count": count,
                "source_semantics_rules": " || ".join(
                    f"{rule}:{rule_count}"
                    for rule, rule_count in sorted(actions.items())
                ),
                "example_records": " || ".join(pattern_examples[labels][:8]),
            }
        )
    return label_rows, pattern_rows


def _source_semantics_split_property_trace(
    records: list[LigatusRecord],
    built_lookup: dict[tuple[str, str], BuiltLigatusRecord],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        if record.ordering_action != "split" or len(record.episode_ids) < 2:
            continue
        built = built_lookup[("segmented_e81", record.record_id)]
        root_labels = _root_label_map(record)
        predecessor_roots = set(record.episode_ids[:-1])
        current_roots = {record.episode_ids[-1]}
        predecessor_counts = _implemented_path_counts(record, predecessor_roots)
        current_counts = _implemented_path_counts(record, current_roots)
        current_e11, _ = evaluate_query(built, "current_modification_retrieval")
        lineage_e11, _ = evaluate_query(built, "lineage_modification_retrieval")
        missing_by_family: dict[str, set[str]] = {
            "E11": lineage_e11 - current_e11,
        }
        for family, local_query, lineage_query in PROPERTY_QUERY_PAIRS:
            local, _ = evaluate_query(built, local_query)
            lineage, _ = evaluate_query(built, lineage_query)
            missing_by_family[family] = lineage - local
        rows.append(
            {
                "record_id": record.record_id,
                "split_cue": record.ordering_rule_id,
                "predecessor_e11_label": " || ".join(
                    root_labels.get(root, root) for root in record.episode_ids[:-1]
                ),
                "current_e11_label": root_labels.get(
                    record.episode_ids[-1], record.episode_ids[-1]
                ),
                "missed_e11": bool(missing_by_family["E11"]),
                "missed_p44": bool(missing_by_family["condition"]),
                "missed_p126": bool(missing_by_family["treatment_material"]),
                "missed_p32": bool(missing_by_family["technique"]),
                "predecessor_path_p44_count": predecessor_counts.get("P44", 0),
                "predecessor_path_p126_count": predecessor_counts.get("P126", 0),
                "predecessor_path_p32_count": predecessor_counts.get("P32", 0),
                "current_path_p44_count": current_counts.get("P44", 0),
                "current_path_p126_count": current_counts.get("P126", 0),
                "current_path_p32_count": current_counts.get("P32", 0),
                "missed_e11_answers": " || ".join(
                    sorted(missing_by_family["E11"])
                ),
                "missed_p44_answers": " || ".join(
                    sorted(missing_by_family["condition"])
                ),
                "missed_p126_answers": " || ".join(
                    sorted(missing_by_family["treatment_material"])
                ),
                "missed_p32_answers": " || ".join(
                    sorted(missing_by_family["technique"])
                ),
            }
        )
    return rows


def _max_split_property_gap_trace(
    records: list[LigatusRecord],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        built = build_profile(record, "segmented_e81")
        events = _event_lookup(record)
        root_labels = _root_label_map(record)
        for family, local_query, lineage_query in PROPERTY_QUERY_PAIRS:
            local, _ = evaluate_query(built, local_query)
            lineage, _ = evaluate_query(built, lineage_query)
            missing = lineage - local
            for answer in sorted(missing):
                event_uri = _event_uri_from_answer(answer)
                event = events.get(event_uri)
                root_id = event.root_event_id if event else ""
                rows.append(
                    {
                        "record_id": record.record_id,
                        "ordering_cue": record.ordering_rule_id,
                        "missing_property_family": family,
                        "missing_answer": answer,
                        "missing_answer_attached_to_root": root_id,
                        "missing_answer_root_label": root_labels.get(root_id, ""),
                        "root_ordered_by": _ordering_basis(record.ordering_rule_id),
                    }
                )
    return rows


def _max_split_property_gap_summary(
    trace_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], Counter] = {}
    ordering: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for row in trace_rows:
        key = (
            row["record_id"],
            row["ordering_cue"],
            row["missing_property_family"],
            row["root_ordered_by"],
        )
        grouped.setdefault(key, Counter())[row["missing_answer_root_label"]] += 1
        ordering.setdefault(
            key,
            {
                "record_id": row["record_id"],
                "ordering_cue": row["ordering_cue"],
                "missing_property_family": row["missing_property_family"],
                "root_ordered_by": row["root_ordered_by"],
            },
        )
    rows = []
    for key in sorted(grouped):
        root_counts = grouped[key]
        rows.append(
            {
                **ordering[key],
                "missing_answer_count": sum(root_counts.values()),
                "missing_answer_attached_to_which_root": " || ".join(
                    f"{root_label}:{count}"
                    for root_label, count in sorted(root_counts.items())
                ),
            }
        )
    return rows


HYPOTHETICAL_ORDER_POLICIES = (
    "hypothetical_treatment_steps_before_component_reattachment",
    "hypothetical_component_reattachment_before_treatment_steps",
)


def _is_unordered_treatment_reattachment_pair(record: LigatusRecord) -> bool:
    return (
        record.ordering_rule_id == "no_supported_order"
        and record.source_root_count == 2
        and {
            _normal_root_label(label)
            for label in record.source_root_labels
        }
        == {"treatment steps", "component reattachment"}
    )


def _root_id_by_label(record: LigatusRecord) -> dict[str, str]:
    return {
        _normal_root_label(label): root_id
        for root_id, label in zip(record.source_root_ids, record.source_root_labels)
    }


def _root_property_values(
    record: LigatusRecord, root_id: str, family: str
) -> tuple[set[str], set[str]]:
    graph = record.graph
    events = [
        event for event in record.events if event.root_event_id == root_id
    ]
    if family == "condition":
        targets = {
            str(target)
            for event in events
            for target in graph.subjects(
                CRM.P31i_was_modified_by, URIRef(event.event_id)
            )
        }
        values = {
            _label(graph, condition)
            for target_id in targets
            for condition in graph.objects(URIRef(target_id), CRM.P44_has_condition)
        }
        return values, targets
    if family == "treatment_material":
        values = {
            _label(graph, value)
            for event in events
            for value in graph.objects(URIRef(event.event_id), CRM.P126_employed)
        }
        return values, set()
    if family == "technique":
        values = {
            _label(graph, value)
            for event in events
            for value in graph.objects(
                URIRef(event.event_id), CRM.P32_used_general_technique
            )
        }
        return values, set()
    raise ValueError(f"unknown property family: {family}")


def _record_elsewhere_statement_count(record: LigatusRecord, family: str) -> int:
    graph = record.graph
    event_nodes = {URIRef(event.event_id) for event in record.events}
    if family == "condition":
        modified_targets = {
            target
            for event_node in event_nodes
            for target in graph.subjects(CRM.P31i_was_modified_by, event_node)
        }
        return sum(
            1
            for subject, _, _ in graph.triples((None, CRM.P44_has_condition, None))
            if subject not in modified_targets
        )
    if family == "treatment_material":
        return sum(
            1
            for subject, _, _ in graph.triples((None, CRM.P126_employed, None))
            if subject not in event_nodes
        )
    if family == "technique":
        return sum(
            1
            for subject, _, _ in graph.triples(
                (None, CRM.P32_used_general_technique, None)
            )
            if subject not in event_nodes
        )
    raise ValueError(f"unknown property family: {family}")


def _classify_split_property_case(
    predecessor_values: set[str],
    current_values: set[str],
    elsewhere_statement_count: int,
) -> str:
    if not predecessor_values and current_values:
        return "predecessor_empty_current_nonempty"
    if not predecessor_values and not current_values:
        if elsewhere_statement_count:
            return "unreachable_elsewhere"
        return "both_empty"
    if predecessor_values == current_values:
        return "equal_nonempty"
    if predecessor_values <= current_values:
        return "predecessor_values_duplicate_current"
    return "predecessor_values_add_new_answers"


def _source_semantics_split_property_case_trace(
    records: list[LigatusRecord],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        if record.ordering_action != "split" or len(record.episode_ids) < 2:
            continue
        root_labels = _root_label_map(record)
        predecessor_roots = record.episode_ids[:-1]
        current_root = record.episode_ids[-1]
        for family, _, _ in PROPERTY_QUERY_PAIRS:
            predecessor_values: set[str] = set()
            predecessor_targets: set[str] = set()
            for root_id in predecessor_roots:
                values, targets = _root_property_values(record, root_id, family)
                predecessor_values.update(values)
                predecessor_targets.update(targets)
            current_values, current_targets = _root_property_values(
                record, current_root, family
            )
            elsewhere_count = _record_elsewhere_statement_count(record, family)
            rows.append(
                {
                    "record_id": record.record_id,
                    "split_cue": record.ordering_rule_id,
                    "property_family": family,
                    "predecessor_root_labels": " || ".join(
                        root_labels.get(root_id, root_id)
                        for root_id in predecessor_roots
                    ),
                    "current_root_label": root_labels.get(current_root, current_root),
                    "predecessor_answer_count": len(predecessor_values),
                    "current_answer_count": len(current_values),
                    "shared_answer_count": len(
                        predecessor_values & current_values
                    ),
                    "union_answer_count": len(
                        predecessor_values | current_values
                    ),
                    "root_answer_sets_equal": predecessor_values == current_values,
                    "predecessor_values_duplicate_current": bool(
                        predecessor_values
                        and predecessor_values <= current_values
                    ),
                    "both_empty": not predecessor_values and not current_values,
                    "elsewhere_statement_count": elsewhere_count,
                    "case": _classify_split_property_case(
                        predecessor_values, current_values, elsewhere_count
                    ),
                    "predecessor_answers": " || ".join(
                        sorted(predecessor_values)
                    ),
                    "current_answers": " || ".join(sorted(current_values)),
                    "predecessor_target_count": (
                        len(predecessor_targets) if family == "condition" else ""
                    ),
                    "current_target_count": (
                        len(current_targets) if family == "condition" else ""
                    ),
                    "shared_target_count": (
                        len(predecessor_targets & current_targets)
                        if family == "condition"
                        else ""
                    ),
                }
            )
    return rows


def _unordered_root_property_distribution(
    records: list[LigatusRecord],
) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        if not _is_unordered_treatment_reattachment_pair(record):
            continue
        roots = _root_id_by_label(record)
        treatment_root = roots["treatment steps"]
        reattachment_root = roots["component reattachment"]
        for family in ("condition", "treatment_material", "technique"):
            treatment_values, treatment_targets = _root_property_values(
                record, treatment_root, family
            )
            reattachment_values, reattachment_targets = _root_property_values(
                record, reattachment_root, family
            )
            union_values = treatment_values | reattachment_values
            shared_targets = treatment_targets & reattachment_targets
            rows.append(
                {
                    "record_id": record.record_id,
                    "property_family": family,
                    "treatment_steps_answer_count": len(treatment_values),
                    "component_reattachment_answer_count": len(reattachment_values),
                    "union_answer_count": len(union_values),
                    "root_answer_sets_equal": treatment_values == reattachment_values,
                    "both_empty": not union_values,
                    "treatment_steps_target_count": (
                        len(treatment_targets) if family == "condition" else ""
                    ),
                    "component_reattachment_target_count": (
                        len(reattachment_targets) if family == "condition" else ""
                    ),
                    "shared_target_count": (
                        len(shared_targets) if family == "condition" else ""
                    ),
                }
            )
    return rows


def _hypothetical_order_sensitivity(
    source_records: list[LigatusRecord],
    records_by_policy: dict[str, list[LigatusRecord]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    unordered_record_ids = {
        record.record_id
        for record in source_records
        if _is_unordered_treatment_reattachment_pair(record)
    }
    source_by_id = {record.record_id: record for record in source_records}
    detail_rows: list[dict[str, Any]] = []
    summary_counter: dict[tuple[str, str, str], Counter] = {}

    for policy_id in HYPOTHETICAL_ORDER_POLICIES:
        for record in records_by_policy.get(policy_id, []):
            if record.record_id not in unordered_record_ids:
                continue
            if len(record.episode_ids) != 2 or record.ordering_action != "split":
                continue
            built = build_profile(record, "segmented_e81")
            source_record = source_by_id[record.record_id]
            root_label_pattern = " || ".join(
                _normal_root_label(label) for label in source_record.source_root_labels
            )
            predecessor_label, current_label = record.episode_labels
            for family, local_query, lineage_query in (
                ("treatment_history", "current_treatment_history", "lineage_treatment_history"),
                ("E11", "current_modification_retrieval", "lineage_modification_retrieval"),
                *PROPERTY_QUERY_PAIRS,
            ):
                local, _ = evaluate_query(built, local_query)
                lineage, _ = evaluate_query(built, lineage_query)
                missing = lineage - local
                key = (policy_id, family, local_query)
                summary = summary_counter.setdefault(key, Counter())
                summary["record_count"] += 1
                summary["local_answer_count"] += len(local)
                summary["lineage_answer_count"] += len(lineage)
                summary["missing_answer_count"] += len(missing)
                summary["gap_record_count"] += bool(missing)
                detail_rows.append(
                    {
                        "record_id": record.record_id,
                        "source_root_label_pattern": root_label_pattern,
                        "hypothetical_order_policy_id": policy_id,
                        "hypothetical_order_label": record.ordering_rule_label,
                        "predecessor_root_label": predecessor_label,
                        "current_root_label": current_label,
                        "query_family": family,
                        "local_query_id": local_query,
                        "lineage_query_id": lineage_query,
                        "local_answer_count": len(local),
                        "lineage_answer_count": len(lineage),
                        "missing_answer_count": len(missing),
                        "has_gap": bool(missing),
                        "missing_answers": " || ".join(sorted(missing)),
                    }
                )

    summary_rows = []
    for (policy_id, family, local_query), counts in sorted(summary_counter.items()):
        record_count = counts["record_count"]
        summary_rows.append(
            {
                "hypothetical_order_policy_id": policy_id,
                "query_family": family,
                "local_query_id": local_query,
                "record_count": record_count,
                "gap_record_count": counts["gap_record_count"],
                "gap_record_rate": (
                    counts["gap_record_count"] / record_count if record_count else 0
                ),
                "local_answer_count": counts["local_answer_count"],
                "lineage_answer_count": counts["lineage_answer_count"],
                "missing_answer_count": counts["missing_answer_count"],
            }
        )

    by_query: dict[str, list[dict[str, Any]]] = {}
    for row in summary_rows:
        by_query.setdefault(row["local_query_id"], []).append(row)
    range_rows = []
    for local_query, rows in sorted(by_query.items()):
        if len(rows) != len(HYPOTHETICAL_ORDER_POLICIES):
            continue
        min_row = min(rows, key=lambda row: int(row["gap_record_count"]))
        max_row = max(rows, key=lambda row: int(row["gap_record_count"]))
        min_missing = min(rows, key=lambda row: int(row["missing_answer_count"]))
        max_missing = max(rows, key=lambda row: int(row["missing_answer_count"]))
        range_rows.append(
            {
                "local_query_id": local_query,
                "query_family": min_row["query_family"],
                "record_count": min_row["record_count"],
                "min_gap_record_count": min_row["gap_record_count"],
                "max_gap_record_count": max_row["gap_record_count"],
                "min_gap_record_rate": min_row["gap_record_rate"],
                "max_gap_record_rate": max_row["gap_record_rate"],
                "order_at_min_gap": min_row["hypothetical_order_policy_id"],
                "order_at_max_gap": max_row["hypothetical_order_policy_id"],
                "min_missing_answer_count": min_missing["missing_answer_count"],
                "max_missing_answer_count": max_missing["missing_answer_count"],
                "order_at_min_missing_answers": min_missing[
                    "hypothetical_order_policy_id"
                ],
                "order_at_max_missing_answers": max_missing[
                    "hypothetical_order_policy_id"
                ],
            }
        )
    return detail_rows, summary_rows, range_rows


def _ordering_audit_rows(records: list[LigatusRecord]) -> list[dict[str, Any]]:
    return [
        {
            "record_id": record.record_id,
            "source_file": str(record.source_path),
            "ordering_policy_id": record.ordering_policy_id,
            "source_root_count": record.source_root_count,
            "ordering_rule_id": record.ordering_rule_id,
            "ordering_rule": record.ordering_rule_label,
            "action": record.ordering_action,
            "resulting_episode_count": len(record.episode_ids),
            "root_ids": " || ".join(record.source_root_ids),
            "root_labels": " || ".join(record.source_root_labels),
            "root_dates": _join_audit_values(record.source_root_dates),
        }
        for record in records
    ]


def _predicate_path_coverage(
    records: list[LigatusRecord], config: dict[str, Any]
) -> list[dict[str, Any]]:
    mapping = {
        key: URIRef(value) for key, value in config["canonical_mapping"].items()
    }
    specifications = (
        ("P44", mapping["condition"], "target"),
        ("P126", mapping["employed_material"], "event"),
        ("P32", mapping["technique"], "event"),
    )
    rows = []
    for predicate_id, predicate, captured_location in specifications:
        counts = Counter()
        for record in records:
            events = set(
                record.graph.subjects(RDF.type, mapping["modification_class"])
            )
            targets = {
                target
                for event in events
                for target in record.graph.subjects(mapping["modified_by"], event)
            }
            for subject, _, _ in record.graph.triples((None, predicate, None)):
                if subject in targets:
                    counts["target"] += 1
                elif subject in events:
                    counts["event"] += 1
                else:
                    counts["elsewhere"] += 1
        captured = counts[captured_location]
        total = sum(counts.values())
        rows.append(
            {
                "predicate_id": predicate_id,
                "predicate_uri": str(predicate),
                "attached_to_target": counts["target"],
                "attached_to_event": counts["event"],
                "attached_elsewhere": counts["elsewhere"],
                "captured_location": captured_location,
                "captured_statement_count": captured,
                "uncaptured_statement_count": total - captured,
                "all_statements_captured": captured == total,
            }
        )
    return rows


def run(config_path: Path, data_dir: Path, output_root: Path) -> dict[str, Any]:
    source_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    ordering_manifest = load_ordering_manifest(config_path)
    primary_policy = ordering_manifest["primary_policy"]
    records = load_records(config_path, data_dir, order_policy=primary_policy)
    ligatus_root = output_root / "ligatus"
    results_dir = ligatus_root / "results"
    graphs_dir = ligatus_root / "profile_graphs"
    for directory in (results_dir, graphs_dir):
        directory.mkdir(parents=True, exist_ok=True)
    write_canonical_table(results_dir / "canonical_treatment_event_table.csv", records)
    profiles = ("persistent_e11", "segmented_e81")
    query_rows = []
    profile_graphs = {profile: Graph() for profile in profiles}
    built_lookup = {}
    for record in records:
        for profile in profiles:
            built = build_profile(record, profile)
            built_lookup[(profile, record.record_id)] = built
            profile_graphs[profile] += built.graph
            for query_id in QUERY_LABELS:
                answers, runtime = evaluate_query(built, query_id)
                query_rows.append(
                    {
                        "profile_id": profile,
                        "record_id": record.record_id,
                        "query_id": query_id,
                        "answer_count": len(answers),
                        "answer_values": " || ".join(sorted(answers)),
                        "runtime_ms": runtime,
                    }
                )
    for profile, graph in profile_graphs.items():
        graph.serialize(graphs_dir / f"{profile}.ttl", format="turtle")
    _write_csv(results_dir / "query_results.csv", query_rows)

    answer_map = _answer_map(query_rows)
    comparison_rows = []
    for query_id in QUERY_LABELS:
        divergent_records = 0
        persistent_answers, segmented_answers = set(), set()
        for record in records:
            left = answer_map[("persistent_e11", record.record_id, query_id)]
            right = answer_map[("segmented_e81", record.record_id, query_id)]
            persistent_answers.update((record.record_id, value) for value in left)
            segmented_answers.update((record.record_id, value) for value in right)
            divergent_records += left != right
        union = persistent_answers | segmented_answers
        comparison_rows.append(
            {
                "query_id": query_id,
                "persistent_answer_count": len(persistent_answers),
                "segmented_answer_count": len(segmented_answers),
                "intersection_count": len(persistent_answers & segmented_answers),
                "union_count": len(union),
                "jaccard_overlap": (
                    len(persistent_answers & segmented_answers) / len(union)
                    if union
                    else 1
                ),
                "divergent_record_count": divergent_records,
                "divergent_record_rate": divergent_records / len(records),
            }
        )
    _write_csv(results_dir / "profile_comparison.csv", comparison_rows)

    local_lineage_rows = []
    for profile in profiles:
        for local_query, lineage_query in LOCAL_LINEAGE_PAIRS:
            affected = 0
            local_count = lineage_count = 0
            for record in records:
                local = answer_map[(profile, record.record_id, local_query)]
                lineage = answer_map[(profile, record.record_id, lineage_query)]
                affected += local != lineage
                local_count += len(local)
                lineage_count += len(lineage)
            local_lineage_rows.append(
                {
                    "profile_id": profile,
                    "local_query_id": local_query,
                    "lineage_query_id": lineage_query,
                    "local_answer_count": local_count,
                    "lineage_answer_count": lineage_count,
                    "records_with_local_lineage_gap": affected,
                    "local_lineage_gap_rate": affected / len(records),
                }
            )
    _write_csv(results_dir / "local_lineage_metrics.csv", local_lineage_rows)
    ordering_audit_rows = _ordering_audit_rows(records)
    _write_csv(results_dir / "episode_order_audit.csv", ordering_audit_rows)
    root_label_rows, two_root_pattern_rows = _root_label_inventory(records)
    _write_csv(results_dir / "source_root_label_inventory.csv", root_label_rows)
    _write_csv(results_dir / "two_root_label_patterns.csv", two_root_pattern_rows)
    path_coverage_rows = _predicate_path_coverage(records, source_config)
    _write_csv(
        results_dir / "predicate_path_coverage.csv", path_coverage_rows
    )

    loo_rows = []
    segmented_gaps = {
        (local_query, lineage_query): {
            record.record_id: (
                answer_map[("segmented_e81", record.record_id, local_query)]
                != answer_map[
                    ("segmented_e81", record.record_id, lineage_query)
                ]
            )
            for record in records
        }
        for local_query, lineage_query in LOCAL_LINEAGE_PAIRS
    }
    for (local_query, lineage_query), gaps in segmented_gaps.items():
        full_count = sum(gaps.values())
        full_rate = full_count / len(gaps)
        loo_rows.append(
            {
                "local_query_id": local_query,
                "lineage_query_id": lineage_query,
                "omitted_record_id": "",
                "gap_record_count": full_count,
                "record_count": len(gaps),
                "gap_rate": full_rate,
                "absolute_shift_from_full": 0,
            }
        )
        for record_id, is_gap in sorted(gaps.items()):
            count = full_count - int(is_gap)
            remaining = len(gaps) - 1
            rate = count / remaining if remaining else 0
            loo_rows.append(
                {
                    "local_query_id": local_query,
                    "lineage_query_id": lineage_query,
                    "omitted_record_id": record_id,
                    "gap_record_count": count,
                    "record_count": remaining,
                    "gap_rate": rate,
                    "absolute_shift_from_full": abs(rate - full_rate),
                }
            )
    _write_csv(results_dir / "leave_one_record_out.csv", loo_rows)

    policy_detail_rows = []
    policy_metric_rows = []
    records_by_policy = {}
    for policy_id, policy in ordering_manifest["policies"].items():
        policy_records = load_records(
            config_path, data_dir, order_policy=policy_id
        )
        records_by_policy[policy_id] = policy_records
        if policy.get("hypothetical_order_sensitivity"):
            continue
        for local_query, lineage_query in LOCAL_LINEAGE_PAIRS:
            gap_count = 0
            local_count = 0
            lineage_count = 0
            for record in policy_records:
                built = build_profile(record, "segmented_e81")
                local, _ = evaluate_query(built, local_query)
                lineage, _ = evaluate_query(built, lineage_query)
                has_gap = local != lineage
                gap_count += has_gap
                local_count += len(local)
                lineage_count += len(lineage)
                policy_detail_rows.append(
                    {
                        "policy_id": policy_id,
                        "record_id": record.record_id,
                        "local_query_id": local_query,
                        "lineage_query_id": lineage_query,
                        "source_root_count": record.source_root_count,
                        "ordering_rule_id": record.ordering_rule_id,
                        "ordering_rule": record.ordering_rule_label,
                        "action": record.ordering_action,
                        "episode_count": len(record.episode_ids),
                        "local_answer_count": len(local),
                        "lineage_answer_count": len(lineage),
                        "has_gap": has_gap,
                    }
                )
            policy_metric_rows.append(
                {
                    "policy_id": policy_id,
                    "local_query_id": local_query,
                    "lineage_query_id": lineage_query,
                    "record_count": len(policy_records),
                    "local_answer_count": local_count,
                    "lineage_answer_count": lineage_count,
                    "gap_record_count": gap_count,
                    "gap_rate": gap_count / len(policy_records),
                }
            )
    _write_csv(
        results_dir / "ordering_policy_record_results.csv",
        policy_detail_rows,
    )
    _write_csv(
        results_dir / "ordering_policy_metrics.csv", policy_metric_rows
    )
    source_split_property_rows = _source_semantics_split_property_trace(
        records, built_lookup
    )
    _write_csv(
        results_dir / "source_semantics_split_property_trace.csv",
        source_split_property_rows,
    )
    source_split_property_case_rows = _source_semantics_split_property_case_trace(
        records
    )
    _write_csv(
        results_dir / "source_semantics_split_property_case_trace.csv",
        source_split_property_case_rows,
    )
    max_split_property_rows = _max_split_property_gap_trace(
        records_by_policy["all_roots_split"]
    )
    max_split_property_summary_rows = _max_split_property_gap_summary(
        max_split_property_rows
    )
    _write_csv(
        results_dir / "all_roots_split_property_gap_trace.csv",
        max_split_property_rows,
    )
    _write_csv(
        results_dir / "all_roots_split_property_gap_summary.csv",
        max_split_property_summary_rows,
    )
    (
        hypothetical_order_detail_rows,
        hypothetical_order_summary_rows,
        hypothetical_order_range_rows,
    ) = _hypothetical_order_sensitivity(records, records_by_policy)
    _write_csv(
        results_dir / "unordered_root_hypothetical_order_record_results.csv",
        hypothetical_order_detail_rows,
    )
    _write_csv(
        results_dir / "unordered_root_hypothetical_order_summary.csv",
        hypothetical_order_summary_rows,
    )
    _write_csv(
        results_dir / "unordered_root_hypothetical_order_ranges.csv",
        hypothetical_order_range_rows,
    )
    unordered_property_distribution_rows = _unordered_root_property_distribution(
        records
    )
    _write_csv(
        results_dir / "unordered_root_property_distribution.csv",
        unordered_property_distribution_rows,
    )

    evidence_rows = []
    for record in records:
        built = built_lookup[("segmented_e81", record.record_id)]
        local_episodes, _ = evaluate_query(
            built, "current_treatment_history"
        )
        lineage_episodes, _ = evaluate_query(
            built, "lineage_treatment_history"
        )
        if local_episodes == lineage_episodes:
            continue
        local_modifications, _ = evaluate_query(
            built, "current_modification_retrieval"
        )
        lineage_modifications, _ = evaluate_query(
            built, "lineage_modification_retrieval"
        )
        evidence_rows.append(
            {
                "record_id": record.record_id,
                "source_file": str(record.source_path),
                "source_root_count": record.source_root_count,
                "episode_count": len(record.episode_ids),
                "episode_ids": " || ".join(record.episode_ids),
                "episode_labels": " || ".join(record.episode_labels),
                "ordering_policy_id": record.ordering_policy_id,
                "ordering_rule_id": record.ordering_rule_id,
                "ordering_rule": record.ordering_rule_label,
                "ordering_action": record.ordering_action,
                "root_dates": _join_audit_values(record.source_root_dates),
                "local_treatment_answers": " || ".join(sorted(local_episodes)),
                "lineage_treatment_answers": " || ".join(
                    sorted(lineage_episodes)
                ),
                "lost_treatment_answers": " || ".join(
                    sorted(lineage_episodes - local_episodes)
                ),
                "local_modification_answers": " || ".join(
                    sorted(local_modifications)
                ),
                "lineage_modification_answers": " || ".join(
                    sorted(lineage_modifications)
                ),
                "lost_modification_answers": " || ".join(
                    sorted(lineage_modifications - local_modifications)
                ),
                "relevant_e11_uris": " || ".join(
                    event.event_id for event in record.events
                ),
            }
        )
    _write_csv(
        results_dir / "record_level_evidence.csv", evidence_rows
    )

    manifest = {
        "benchmark_id": "ligatus_reduced_conservation_profile_comparison",
        "status": "external_replication_run",
        "corpus_role": source_config["corpus_role"],
        "source_record_count": len(records),
        "profiles": list(profiles),
        "queries": QUERY_LABELS,
        "segmentation": (
            "Segmented profile creates one resulting identity per supplied "
            "top-level E11 treatment episode. Nested E11 hierarchy is preserved."
        ),
        "lexical_extraction_used": False,
        "source_repository": source_config["repository"],
        "source_repository_commit": source_config["repository_commit"],
        "ordering_policy_manifest_id": ordering_manifest["manifest_id"],
        "ordering_policy_manifest_version": ordering_manifest["version"],
        "primary_ordering_policy": primary_policy,
        "ordering_policies": ordering_manifest["policies"],
        "machine_result_files": [
            "canonical_treatment_event_table.csv",
            "episode_order_audit.csv",
            "leave_one_record_out.csv",
            "local_lineage_metrics.csv",
            "source_root_label_inventory.csv",
            "two_root_label_patterns.csv",
            "ordering_policy_metrics.csv",
            "ordering_policy_record_results.csv",
            "predicate_path_coverage.csv",
            "profile_comparison.csv",
            "query_results.csv",
            "record_level_evidence.csv",
            "source_semantics_split_property_trace.csv",
            "source_semantics_split_property_case_trace.csv",
            "all_roots_split_property_gap_trace.csv",
            "all_roots_split_property_gap_summary.csv",
            "unordered_root_hypothetical_order_record_results.csv",
            "unordered_root_hypothetical_order_summary.csv",
            "unordered_root_hypothetical_order_ranges.csv",
            "unordered_root_property_distribution.csv",
        ],
    }
    (results_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(ligatus_root / "results.md", results_dir)
    write_plots(ligatus_root / "plots", comparison_rows, local_lineage_rows)
    return {
        "records": records,
        "query_rows": query_rows,
        "comparison_rows": comparison_rows,
        "local_lineage_rows": local_lineage_rows,
        "ordering_audit_rows": ordering_audit_rows,
        "loo_rows": loo_rows,
        "ordering_policy_metric_rows": policy_metric_rows,
        "ordering_policy_record_rows": policy_detail_rows,
        "path_coverage_rows": path_coverage_rows,
        "root_label_rows": root_label_rows,
        "two_root_pattern_rows": two_root_pattern_rows,
        "source_split_property_rows": source_split_property_rows,
        "max_split_property_rows": max_split_property_rows,
        "max_split_property_summary_rows": max_split_property_summary_rows,
        "hypothetical_order_detail_rows": hypothetical_order_detail_rows,
        "hypothetical_order_summary_rows": hypothetical_order_summary_rows,
        "hypothetical_order_range_rows": hypothetical_order_range_rows,
        "unordered_property_distribution_rows": unordered_property_distribution_rows,
        "evidence_rows": evidence_rows,
    }


def write_plots(
    plots_dir: Path,
    comparisons: list[dict[str, Any]],
    local_lineage: list[dict[str, Any]],
) -> None:
    plots_dir.mkdir(parents=True, exist_ok=True)
    labels = [
        "treatment history",
        "modifications",
        "condition→treatment",
        "materials over time",
        "techniques over time",
    ]
    segmented = [
        row
        for row in local_lineage
        if row["profile_id"] == "segmented_e81"
    ]
    width, height = 980, 520
    left, right, top, bottom = 90, 40, 55, 135
    plot_w, plot_h = width - left - right, height - top - bottom
    group_w = plot_w / len(labels)
    max_y = max(int(row["lineage_answer_count"]) for row in segmented)
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="19" font-weight="600">Ligatus segmented profile: local versus lineage answers</text>',
    ]
    for index, (label, row) in enumerate(zip(labels, segmented)):
        x = left + index * group_w + group_w * 0.2
        local_h = int(row["local_answer_count"]) / max_y * plot_h
        lineage_h = int(row["lineage_answer_count"]) / max_y * plot_h
        svg.extend(
            [
                f'<rect x="{x}" y="{top+plot_h-local_h}" width="{group_w*0.25}" height="{local_h}" fill="#d9480f"/>',
                f'<rect x="{x+group_w*0.29}" y="{top+plot_h-lineage_h}" width="{group_w*0.25}" height="{lineage_h}" fill="#1971c2"/>',
                f'<text x="{x+group_w*0.27}" y="{top+plot_h+22}" text-anchor="middle" font-family="sans-serif" font-size="11" transform="rotate(28 {x+group_w*0.27} {top+plot_h+22})">{label}</text>',
            ]
        )
    svg.extend(
        [
            f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#333"/>',
            f'<rect x="{width-210}" y="50" width="15" height="15" fill="#d9480f"/><text x="{width-188}" y="63" font-family="sans-serif" font-size="12">current-local</text>',
            f'<rect x="{width-110}" y="50" width="15" height="15" fill="#1971c2"/><text x="{width-88}" y="63" font-family="sans-serif" font-size="12">lineage</text>',
            "</svg>",
        ]
    )
    (plots_dir / "local_vs_lineage_answers.svg").write_text(
        "\n".join(svg), encoding="utf-8"
    )

    width, height = 900, 470
    left, right, top, bottom = 90, 40, 55, 120
    plot_w, plot_h = width - left - right, height - top - bottom
    bar_w = plot_w / len(comparisons) * 0.62
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="28" text-anchor="middle" font-family="sans-serif" font-size="19" font-weight="600">Records whose answers differ between persistent and segmented profiles</text>',
    ]
    for index, row in enumerate(comparisons):
        rate = float(row["divergent_record_rate"])
        x = left + index * plot_w / len(comparisons) + 12
        h = rate * plot_h
        svg.append(
            f'<rect x="{x}" y="{top+plot_h-h}" width="{bar_w}" height="{h}" fill="#6741d9"/>'
        )
        svg.append(
            f'<text x="{x+bar_w/2}" y="{top+plot_h-h-6}" text-anchor="middle" font-family="sans-serif" font-size="10">{rate:.1%}</text>'
        )
        short = row["query_id"].replace("current_", "local ").replace(
            "lineage_", "lineage "
        )
        svg.append(
            f'<text x="{x+bar_w/2}" y="{top+plot_h+18}" text-anchor="start" transform="rotate(48 {x+bar_w/2} {top+plot_h+18})" font-family="sans-serif" font-size="9">{short}</text>'
        )
    svg.extend(
        [
            f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#333"/>',
            "</svg>",
        ]
    )
    (plots_dir / "profile_divergence_rates.svg").write_text(
        "\n".join(svg), encoding="utf-8"
    )


def _read_csv_required(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"required result file is missing: {path}")
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json_required(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"required result file is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _count_rate(count: int, total: int) -> str:
    return f"{count}/{total} ({count / total:.1%})"


def _policy_episode_counts(records: list[dict[str, str]]) -> tuple[int, int, int]:
    one_episode = sum(int(row["episode_count"]) == 1 for row in records)
    split = sum(row["action"] == "split" for row in records)
    collapsed = sum(row["action"] == "collapse" for row in records)
    return one_episode, split, collapsed


def _leave_one_out_range(records: list[dict[str, str]]) -> str:
    gap_count = sum(row["has_gap"] == "True" for row in records)
    rates = [
        (gap_count - int(row["has_gap"] == "True")) / (len(records) - 1)
        for row in records
    ]
    return f"{min(rates):.1%}-{max(rates):.1%}"


def write_report(path: Path, results_dir: Path) -> None:
    manifest = _read_json_required(results_dir / "manifest.json")
    canonical = _read_csv_required(results_dir / "canonical_treatment_event_table.csv")
    comparisons = _read_csv_required(results_dir / "profile_comparison.csv")
    local_lineage = _read_csv_required(results_dir / "local_lineage_metrics.csv")
    ordering_audit = _read_csv_required(results_dir / "episode_order_audit.csv")
    loo_rows = _read_csv_required(results_dir / "leave_one_record_out.csv")
    policy_metrics = _read_csv_required(results_dir / "ordering_policy_metrics.csv")
    policy_records = _read_csv_required(
        results_dir / "ordering_policy_record_results.csv"
    )
    path_coverage = _read_csv_required(results_dir / "predicate_path_coverage.csv")
    evidence = _read_csv_required(results_dir / "record_level_evidence.csv")
    source_split_property_trace = _read_csv_required(
        results_dir / "source_semantics_split_property_trace.csv"
    )
    source_split_property_case_trace = _read_csv_required(
        results_dir / "source_semantics_split_property_case_trace.csv"
    )
    max_split_property_trace = _read_csv_required(
        results_dir / "all_roots_split_property_gap_trace.csv"
    )
    max_split_property_summary = _read_csv_required(
        results_dir / "all_roots_split_property_gap_summary.csv"
    )
    hypothetical_order_ranges = _read_csv_required(
        results_dir / "unordered_root_hypothetical_order_ranges.csv"
    )
    hypothetical_order_summary = _read_csv_required(
        results_dir / "unordered_root_hypothetical_order_summary.csv"
    )
    unordered_property_distribution = _read_csv_required(
        results_dir / "unordered_root_property_distribution.csv"
    )

    record_count = int(manifest["source_record_count"])
    source_rows = [
        row
        for row in ordering_audit
        if row["ordering_policy_id"] == "source_semantics"
    ]
    two_root_rows = [row for row in source_rows if int(row["source_root_count"]) == 2]
    source_rule_counts = Counter(row["ordering_rule_id"] for row in two_root_rows)
    one_episode = sum(int(row["resulting_episode_count"]) == 1 for row in source_rows)
    two_episode = sum(int(row["resulting_episode_count"]) == 2 for row in source_rows)
    episode_identifiers = sum(
        int(row["resulting_episode_count"]) for row in source_rows
    )

    comparisons_by_query = {row["query_id"]: row for row in comparisons}
    current_treatment = comparisons_by_query["current_treatment_history"]
    current_e11 = comparisons_by_query["current_modification_retrieval"]
    lineage_treatment = comparisons_by_query["lineage_treatment_history"]
    lineage_e11 = comparisons_by_query["lineage_modification_retrieval"]
    persistent_history = next(
        row
        for row in local_lineage
        if row["profile_id"] == "persistent_e11"
        and row["local_query_id"] == "current_treatment_history"
    )

    policy_metric = {
        (row["policy_id"], row["local_query_id"]): row for row in policy_metrics
    }
    main_policy_ids = ("dated_only", "source_semantics")
    records_by_policy = {
        policy_id: [row for row in policy_records if row["policy_id"] == policy_id]
        for policy_id in main_policy_ids
    }
    table_rows = []
    for policy_id in main_policy_ids:
        records = [
            row
            for row in records_by_policy[policy_id]
            if row["local_query_id"] == "current_treatment_history"
        ]
        one_count, split_count, collapsed_count = _policy_episode_counts(records)
        history = policy_metric[(policy_id, "current_treatment_history")]
        e11 = policy_metric[(policy_id, "current_modification_retrieval")]
        condition = policy_metric[(policy_id, "current_condition_to_treatment")]
        if history["gap_record_count"] != e11["gap_record_count"]:
            raise ValueError(f"history and E11 gaps differ for {policy_id}")
        table_rows.append(
            "| {policy} | {episodes} | {history_gap} | {property_gap} | {loso} |".format(
                policy=(
                    f"`{policy_id}` "
                    f"(`{manifest['ordering_policies'][policy_id]['label']}`)"
                ),
                episodes=f"{one_count} / {split_count} / {collapsed_count}",
                history_gap=_count_rate(
                    int(history["gap_record_count"]),
                    int(history["record_count"]),
                ),
                property_gap=(
                    f"{condition['gap_record_count']}/"
                    f"{condition['record_count']} each"
                ),
                loso=_leave_one_out_range(records),
            )
        )

    primary_loo = [
        row
        for row in loo_rows
        if row["local_query_id"] == "current_treatment_history"
        and row["omitted_record_id"]
    ]
    omit_divergent = next(row for row in primary_loo if row["gap_record_count"] == "10")
    omit_non_divergent = next(
        row for row in primary_loo if row["gap_record_count"] == "11"
    )
    coverage = {row["predicate_id"]: row for row in path_coverage}
    evidence_rules = Counter(row["ordering_rule_id"] for row in evidence)
    date_split_record = next(
        row["record_id"] for row in evidence if row["ordering_rule_id"] == "parsed_dates"
    )
    hypothetical_ranges_by_family = {
        row["query_family"]: row for row in hypothetical_order_ranges
    }
    hypothetical_record_count = int(
        next(iter(hypothetical_order_ranges))["record_count"]
    )
    hypothetical_order_count = len(
        {
            row["hypothetical_order_policy_id"]
            for row in hypothetical_order_summary
        }
    )
    hypothetical_record_order_count = hypothetical_record_count * hypothetical_order_count
    unordered_both_empty = Counter(
        row["property_family"]
        for row in unordered_property_distribution
        if row["both_empty"] == "True"
    )
    cued_property_cases = Counter(
        row["case"] for row in source_split_property_case_trace
    )
    unordered_equal = Counter(
        row["property_family"]
        for row in unordered_property_distribution
        if row["root_answer_sets_equal"] == "True"
    )
    unordered_condition_rows = [
        row
        for row in unordered_property_distribution
        if row["property_family"] == "condition"
    ]
    condition_treatment_zero_targets = sum(
        row["treatment_steps_target_count"] == "0"
        for row in unordered_condition_rows
    )
    condition_reattachment_one_target = sum(
        row["component_reattachment_target_count"] == "1"
        for row in unordered_condition_rows
    )
    condition_zero_shared_targets = sum(
        row["shared_target_count"] == "0"
        for row in unordered_condition_rows
    )
    current_gap_count = int(current_treatment["divergent_record_count"])
    if current_gap_count != int(current_e11["divergent_record_count"]):
        raise ValueError("current treatment and E11 divergence counts differ")
    if (
        float(lineage_treatment["jaccard_overlap"]) != 1.0
        or float(lineage_e11["jaccard_overlap"]) != 1.0
    ):
        raise ValueError("lineage-wide answer sets are expected to match")
    if int(persistent_history["records_with_local_lineage_gap"]) != 0:
        raise ValueError("persistent current-local and lineage answers diverge")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Results

The external Ligatus evaluation used {record_count} RDF records from the Linked Conservation Data board reattachment corpus. The adapter extracted {len(canonical)} E11 Modification events. Of the {record_count} records, {sum(int(row["source_root_count"]) == 1 for row in source_rows)} had one source root E11 activity. The remaining {len(two_root_rows)} records had two source roots. Under `source_semantics`, {source_rule_counts["previous_repair_before_main_event"]} two-root records were split by the previous repair/main conservation event label rule, {source_rule_counts["parsed_dates"]} was split by dates, and {source_rule_counts["no_supported_order"]} were collapsed because no supported order was found. This produced {one_episode} one-episode records, {two_episode} two-episode records, and {episode_identifiers} treatment episode identifiers.

Under `source_semantics`, current-identity-local treatment history and E11 retrieval differed between the persistent and segmented profiles in the same {current_gap_count} of {record_count} records, or {float(current_treatment["divergent_record_rate"]):.1%}. In those records, the segmented current-identity-local treatment query lacked one earlier episode identifier, and the E11 query lacked one earlier E11 URI. The lineage-wide treatment-history and E11 answer sets were identical across the two profiles, with Jaccard similarity {float(lineage_treatment["jaccard_overlap"]):.3f}. In the persistent profile, current-identity-local and lineage-wide answers did not diverge.

For treatment history and E11 retrieval, the same records diverged under each evidence policy. Table 1 therefore reports these two query families in a single gap column. The three property-retrieval tasks are grouped because condition, treatment material, and technique retrieval had the same divergent-record count within each policy.

| Episode-segmentation policy | Episodes | History/E11 gap | Property gap | LOSO |
|---|---:|---:|---:|---:|
{chr(10).join(table_rows)}

The leave-one-record-out diagnostic was computed from record level gap indicators. The profiles and ordering decisions were not rebuilt for each omission. Under `source_semantics`, omitting one of the {len(evidence)} divergent records gave {omit_divergent["gap_record_count"]}/{omit_divergent["record_count"]} divergent records, or {float(omit_divergent["gap_rate"]):.1%}. Omitting any non-divergent record gave {omit_non_divergent["gap_record_count"]}/{omit_non_divergent["record_count"]} divergent records, or {float(omit_non_divergent["gap_rate"]):.1%}.

The property result is path-limited and diagnostic. A zero property gap under `source_semantics` means that no additional answers were found on predecessor identities along the implemented P44, P126, and P32 paths; it does not show that condition, material, or technique information is generally unaffected by segmentation. The predicate-path inventory counted the source statements used by the three property-retrieval tasks. The condition task used {coverage["P44"]["attached_to_target"]} P44 statements attached to modified targets, while {coverage["P44"]["attached_elsewhere"]} P44 statements occurred elsewhere. The material task used {coverage["P126"]["attached_to_event"]} P126 statements attached directly to E11 events, while {coverage["P126"]["attached_elsewhere"]} P126 statements occurred elsewhere. The technique task used {coverage["P32"]["attached_to_event"]} P32 statements attached directly to E11 events, while {coverage["P32"]["attached_elsewhere"]} P32 statements occurred elsewhere.

The {source_rule_counts["no_supported_order"]} no-supported-order records were audited separately rather than assigned an arbitrary current episode. They are consistently two-root records with `Treatment Steps` and `Component Reattachment` as the two source-root labels. The hypothetical order sensitivity diagnostic enumerated both possible two-root sequences for these {hypothetical_record_count} records, giving {hypothetical_record_order_count} record-order evaluations. Across the two hypothetical orders, treatment-history gaps ranged from {hypothetical_ranges_by_family["treatment_history"]["min_gap_record_count"]}/{hypothetical_record_count} to {hypothetical_ranges_by_family["treatment_history"]["max_gap_record_count"]}/{hypothetical_record_count} records, and E11 gaps ranged from {hypothetical_ranges_by_family["E11"]["min_gap_record_count"]}/{hypothetical_record_count} to {hypothetical_ranges_by_family["E11"]["max_gap_record_count"]}/{hypothetical_record_count}. Property gaps ranged from {hypothetical_ranges_by_family["condition"]["min_gap_record_count"]}/{hypothetical_record_count} to {hypothetical_ranges_by_family["condition"]["max_gap_record_count"]}/{hypothetical_record_count} for condition, {hypothetical_ranges_by_family["treatment_material"]["min_gap_record_count"]}/{hypothetical_record_count} to {hypothetical_ranges_by_family["treatment_material"]["max_gap_record_count"]}/{hypothetical_record_count} for material, and {hypothetical_ranges_by_family["technique"]["min_gap_record_count"]}/{hypothetical_record_count} to {hypothetical_ranges_by_family["technique"]["max_gap_record_count"]}/{hypothetical_record_count} for technique. These ranges are reported as hypothetical order sensitivity, not as historical segmentation evidence. The file `unordered_root_property_distribution.csv` explains the property stability: root-level value sets were equal in {unordered_equal["condition"]}/{hypothetical_record_count} condition rows, {unordered_equal["treatment_material"]}/{hypothetical_record_count} material rows, and {unordered_equal["technique"]}/{hypothetical_record_count} technique rows; both root value sets were empty in {unordered_both_empty["condition"]}/{hypothetical_record_count}, {unordered_both_empty["treatment_material"]}/{hypothetical_record_count}, and {unordered_both_empty["technique"]}/{hypothetical_record_count} rows, respectively. For the P44 path, `Treatment Steps` had zero modified targets in {condition_treatment_zero_targets}/{hypothetical_record_count} rows, `Component Reattachment` had one modified target in {condition_reattachment_one_target}/{hypothetical_record_count} rows, and the two roots shared zero modified targets in {condition_zero_shared_targets}/{hypothetical_record_count} rows.

The evidence ledger for `source_semantics` contains {len(evidence)} divergent records. {evidence_rules["previous_repair_before_main_event"]} were split by the previous repair/main conservation event label rule, and one, `{date_split_record}`, was split by dates. The file `source_semantics_split_property_trace.csv` reports the predecessor/current E11 labels and implemented-path P44, P126, and P32 counts for these {len(source_split_property_trace)} split records. The file `source_semantics_split_property_case_trace.csv` classifies the {len(source_split_property_case_trace)} split-record property-family cases: {cued_property_cases["predecessor_empty_current_nonempty"]} predecessor-empty/current-nonempty, {cued_property_cases["both_empty"]} both-empty, {cued_property_cases["equal_nonempty"]} equal-nonempty, {cued_property_cases["predecessor_values_duplicate_current"]} predecessor-duplicate-current, and {cued_property_cases["unreachable_elsewhere"]} unreachable-elsewhere. The file `all_roots_split_property_gap_summary.csv` reports the {len(max_split_property_summary)} record-family gaps in the max-split diagnostic; `all_roots_split_property_gap_trace.csv` expands these to {len(max_split_property_trace)} missing property answers and resolves each answer to the source root that carried it.
""",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("data/ligatus/board_pilot.yaml"),
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    run(args.config, args.data_dir, args.output_root)


if __name__ == "__main__":
    main()
