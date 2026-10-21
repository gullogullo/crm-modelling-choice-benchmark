from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urljoin
import xml.etree.ElementTree as ET


RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XML_NS = "http://www.w3.org/XML/1998/namespace"


@dataclass(frozen=True, order=True)
class Term:
    kind: str
    value: str
    datatype: str = ""
    language: str = ""


@dataclass(frozen=True, order=True)
class Triple:
    subject: Term
    predicate: str
    object: Term


@dataclass(frozen=True)
class IndexEvidence:
    rule_id: str
    component: Term
    e11: Term
    p46_depth: int


@dataclass
class RecordResult:
    record_id: str
    described_object: Term
    source: set[Triple]
    index_triples: set[Triple]
    index_provenance: dict[Triple, set[IndexEvidence]]
    fully_articulated_path_answers: dict[str, set[Term]]
    index_answers: dict[str, set[Term]]
    documented_answer_universe: dict[str, set[Term]]

    @property
    def index_recovered_answers(self) -> dict[str, set[Term]]:
        return {
            family: (
                self.index_answers[family]
                - self.fully_articulated_path_answers[family]
            )
            for family in self.index_answers
        }


class RdfXmlParser:
    def __init__(self, path: Path, blank_scope: str = ""):
        self.path = path
        self.base = path.resolve().as_uri()
        self.triples: set[Triple] = set()
        self.blank_counter = 0
        self.node_ids: dict[str, Term] = {}
        self.blank_prefix = hashlib.sha256(
            (blank_scope or path.name).encode("utf-8")
        ).hexdigest()[:12]

    def parse(self) -> set[Triple]:
        root = ET.parse(self.path).getroot()
        self.base = root.attrib.get(f"{{{XML_NS}}}base", self.base)
        for child in root:
            self._parse_node(child)
        return self.triples

    def _blank(self, node_id: str = "") -> Term:
        if node_id:
            if node_id not in self.node_ids:
                self.node_ids[node_id] = Term(
                    "bnode", f"{self.blank_prefix}_{node_id}"
                )
            return self.node_ids[node_id]
        self.blank_counter += 1
        return Term("bnode", f"{self.blank_prefix}_b{self.blank_counter:06d}")

    def _uri(self, value: str) -> Term:
        return Term("uri", urljoin(self.base, value))

    def _subject(self, element: ET.Element) -> Term:
        about = element.attrib.get(f"{{{RDF_NS}}}about")
        if about is not None:
            return self._uri(about)
        identifier = element.attrib.get(f"{{{RDF_NS}}}ID")
        if identifier is not None:
            return self._uri(f"#{identifier}")
        node_id = element.attrib.get(f"{{{RDF_NS}}}nodeID")
        return self._blank(node_id or "")

    def _parse_node(self, element: ET.Element) -> Term:
        subject = self._subject(element)
        if element.tag != f"{{{RDF_NS}}}Description":
            self.triples.add(
                Triple(subject, f"{RDF_NS}type", Term("uri", _expanded(element.tag)))
            )
        for property_element in element:
            self._parse_property(subject, property_element)
        return subject

    def _parse_property(self, subject: Term, element: ET.Element) -> None:
        predicate = _expanded(element.tag)
        resource = element.attrib.get(f"{{{RDF_NS}}}resource")
        node_id = element.attrib.get(f"{{{RDF_NS}}}nodeID")
        parse_type = element.attrib.get(f"{{{RDF_NS}}}parseType")
        if resource is not None:
            objects = [self._uri(resource)]
        elif node_id is not None:
            objects = [self._blank(node_id)]
        elif parse_type == "Resource":
            nested = self._blank()
            objects = [nested]
            for child in element:
                self._parse_property(nested, child)
        elif list(element):
            objects = [self._parse_node(child) for child in element]
        else:
            objects = [
                Term(
                    "literal",
                    element.text or "",
                    element.attrib.get(f"{{{RDF_NS}}}datatype", ""),
                    element.attrib.get(f"{{{XML_NS}}}lang", ""),
                )
            ]
        for object_term in objects:
            self.triples.add(Triple(subject, predicate, object_term))


def _expanded(tag: str) -> str:
    if tag.startswith("{"):
        namespace, local = tag[1:].split("}", 1)
        return namespace + local
    return tag


def _objects(graph: set[Triple], subject: Term, predicate: str) -> set[Term]:
    return {
        triple.object
        for triple in graph
        if triple.subject == subject and triple.predicate == predicate
    }


def _subjects(graph: set[Triple], predicate: str, object_term: Term) -> set[Term]:
    return {
        triple.subject
        for triple in graph
        if triple.predicate == predicate and triple.object == object_term
    }


def _typed_subjects(graph: set[Triple], class_uri: str, rdf_type: str) -> set[Term]:
    return _subjects(graph, rdf_type, Term("uri", class_uri))


def _described_object_selection(graph: set[Triple], config: dict) -> tuple[Term, dict]:
    predicates = config["predicates"]
    candidates = _typed_subjects(
        graph, config["classes"]["described_object"], predicates["rdf_type"]
    )
    if not candidates:
        raise ValueError("record contains no configured described-object class")
    composition = predicates["composition"]
    production_predicate = predicates["production"]

    def closure_size(candidate: Term) -> int:
        seen = set()
        pending = [candidate]
        while pending:
            node = pending.pop()
            for component in _objects(graph, node, composition):
                if component not in seen:
                    seen.add(component)
                    pending.append(component)
        return len(seen)

    closure_sizes = {candidate: closure_size(candidate) for candidate in candidates}
    maximum = max(closure_sizes.values())
    largest_candidates = {
        candidate for candidate, size in closure_sizes.items() if size == maximum
    }
    production_flags = {
        candidate: bool(_objects(graph, candidate, production_predicate))
        for candidate in largest_candidates
    }
    produced = {
        candidate
        for candidate, has_production in production_flags.items()
        if has_production
    }
    selected_candidates = produced or largest_candidates
    selected = sorted(selected_candidates)[0]

    tie = len(largest_candidates) > 1
    if not tie:
        selection_reason = "unique_largest_closure"
    elif produced and len(produced) == 1:
        selection_reason = "selected_by_P108i"
    else:
        selection_reason = "selected_by_lexical_uri"

    return selected, {
        "candidates": candidates,
        "closure_sizes": closure_sizes,
        "production_flags": production_flags,
        "largest_candidates": largest_candidates,
        "selected": selected,
        "tie": tie,
        "resolved_by_p108i": tie and len(produced) == 1,
        "resolved_by_lexical_uri": tie and not (produced and len(produced) == 1),
        "selection_reason": selection_reason,
    }


def _described_object(graph: set[Triple], config: dict) -> Term:
    selected, _ = _described_object_selection(graph, config)
    return selected


def _described_object_selection_diagnostics(
    results: list[RecordResult], config: dict
) -> tuple[list[dict], list[dict]]:
    metrics = {
        "total_records": 0,
        "records_with_single_E22_candidate": 0,
        "records_with_multiple_E22_candidates": 0,
        "records_unambiguous_by_largest_closure": 0,
        "records_with_largest_closure_tie": 0,
        "ties_resolved_by_P108i": 0,
        "ties_resolved_by_lexical_uri": 0,
    }
    maximum_number_of_tied_candidates = 0
    tie_rows: list[dict] = []

    for result in results:
        selected, diagnostic = _described_object_selection(result.source, config)
        if selected != result.described_object:
            raise ValueError(
                f"described-object selection mismatch for {result.record_id}: "
                f"{selected.value} != {result.described_object.value}"
            )

        metrics["total_records"] += 1
        if len(diagnostic["candidates"]) == 1:
            metrics["records_with_single_E22_candidate"] += 1
        else:
            metrics["records_with_multiple_E22_candidates"] += 1

        if diagnostic["tie"]:
            metrics["records_with_largest_closure_tie"] += 1
            if diagnostic["resolved_by_p108i"]:
                metrics["ties_resolved_by_P108i"] += 1
            if diagnostic["resolved_by_lexical_uri"]:
                metrics["ties_resolved_by_lexical_uri"] += 1
            maximum_number_of_tied_candidates = max(
                maximum_number_of_tied_candidates,
                len(diagnostic["largest_candidates"]),
            )
            for candidate in sorted(diagnostic["largest_candidates"]):
                tie_rows.append(
                    {
                        "record_id": result.record_id,
                        "candidate_uri": candidate.value,
                        "closure_size": diagnostic["closure_sizes"][candidate],
                        "has_P108i": diagnostic["production_flags"][candidate],
                        "selected": candidate == diagnostic["selected"],
                        "selection_reason": (
                            diagnostic["selection_reason"]
                            if candidate == diagnostic["selected"]
                            else "not_selected"
                        ),
                    }
                )
        else:
            metrics["records_unambiguous_by_largest_closure"] += 1
            maximum_number_of_tied_candidates = max(
                maximum_number_of_tied_candidates, 1
            )

    summary_rows = [
        {"metric": "total_records", "value": metrics["total_records"]},
        {"metric": "records_with_single_E22_candidate", "value": metrics["records_with_single_E22_candidate"]},
        {"metric": "records_with_multiple_E22_candidates", "value": metrics["records_with_multiple_E22_candidates"]},
        {"metric": "records_unambiguous_by_largest_closure", "value": metrics["records_unambiguous_by_largest_closure"]},
        {"metric": "records_with_largest_closure_tie", "value": metrics["records_with_largest_closure_tie"]},
        {"metric": "ties_resolved_by_P108i", "value": metrics["ties_resolved_by_P108i"]},
        {"metric": "ties_resolved_by_lexical_uri", "value": metrics["ties_resolved_by_lexical_uri"]},
        {"metric": "maximum_number_of_tied_candidates", "value": maximum_number_of_tied_candidates},
    ]
    return summary_rows, tie_rows


def _labels(graph: set[Triple], label_predicate: str) -> dict[Term, str]:
    result = {}
    for triple in sorted(graph):
        if triple.predicate == label_predicate and triple.object.kind == "literal":
            result.setdefault(triple.subject, triple.object.value)
    return result


def _p46_depths(
    graph: set[Triple], described_object: Term, composition_predicate: str
) -> dict[Term, int]:
    depths = {described_object: 0}
    pending = [described_object]
    while pending:
        node = pending.pop(0)
        for component in sorted(_objects(graph, node, composition_predicate)):
            proposed = depths[node] + 1
            if component not in depths or proposed < depths[component]:
                depths[component] = proposed
                pending.append(component)
    return depths


def _materialise_indexes(
    graph: set[Triple], described_object: Term, config: dict
) -> tuple[set[Triple], dict[Triple, set[IndexEvidence]]]:
    predicates = config["predicates"]
    modifications = _typed_subjects(
        graph, config["classes"]["modification"], predicates["rdf_type"]
    )
    indexes: set[Triple] = set()
    provenance: dict[Triple, set[IndexEvidence]] = defaultdict(set)
    rule_by_role = {
        rule["role"]: rule["id"]
        for rule in config["index_rules"]
    }
    required_roles = {"e11_index", "condition_index"}
    if required_roles - set(rule_by_role):
        raise ValueError(
            "required index roles are absent from configuration"
        )
    modification_rule = rule_by_role["e11_index"]
    condition_rule = rule_by_role["condition_index"]
    p46_depths = _p46_depths(graph, described_object, predicates["composition"])
    p46_components = set(p46_depths) - {described_object}

    for event in sorted(modifications):
        component_targets = (
            _subjects(graph, predicates["modified_by"], event) & p46_components
        )
        for component in component_targets:
            event_index = Triple(
                described_object, predicates["index_modification"], event
            )
            indexes.add(event_index)
            provenance[event_index].add(
                IndexEvidence(
                    modification_rule,
                    component,
                    event,
                    p46_depths[component],
                )
            )
            for condition in _objects(graph, component, predicates["condition"]):
                condition_index = Triple(
                    described_object, predicates["index_condition"], condition
                )
                indexes.add(condition_index)
                provenance[condition_index].add(
                    IndexEvidence(
                        condition_rule,
                        component,
                        event,
                        p46_depths[component],
                    )
                )
    return indexes, dict(provenance)


def _query(graph: set[Triple], described_object: Term, config: dict) -> dict[str, set[Term]]:
    predicates = config["predicates"]
    modifications = (
        _objects(graph, described_object, predicates["modified_by"])
        | _objects(graph, described_object, predicates["index_modification"])
    )
    e11 = Term("uri", config["classes"]["modification"])
    modifications = {
        event
        for event in modifications
        if Triple(event, predicates["rdf_type"], e11) in graph
    }
    return {
        "e11_modification": modifications,
        "condition": (
            _objects(graph, described_object, predicates["condition"])
            | _objects(graph, described_object, predicates["index_condition"])
        ),
        "material": {
            value
            for event in modifications
            for value in _objects(graph, event, predicates["material"])
        },
        "technique": {
            value
            for event in modifications
            for value in _objects(graph, event, predicates["technique"])
        },
    }


def _documented_answer_universe(
    graph: set[Triple], config: dict
) -> dict[str, set[Term]]:
    predicates = config["predicates"]
    return {
        "e11_modification": _typed_subjects(
            graph,
            config["classes"]["modification"],
            predicates["rdf_type"],
        ),
        "condition": {
            triple.object
            for triple in graph
            if triple.predicate == predicates["condition"]
        },
        "material": {
            triple.object
            for triple in graph
            if triple.predicate == predicates["material"]
        },
        "technique": {
            triple.object
            for triple in graph
            if triple.predicate == predicates["technique"]
        },
    }
def _record_id(path: Path, source_dir: Path) -> str:
    relative = path.relative_to(source_dir)
    institution = relative.parts[0] if len(relative.parts) > 2 else path.parent.name
    return f"{institution}:{path.stem}"


def process_record(path: Path, source_dir: Path, config: dict) -> RecordResult:
    record_id = _record_id(path, source_dir)
    source = RdfXmlParser(path, blank_scope=record_id).parse()
    described_object = _described_object(source, config)
    indexes, provenance = _materialise_indexes(
        source, described_object, config
    )
    return RecordResult(
        record_id=record_id,
        described_object=described_object,
        source=source,
        index_triples=indexes,
        index_provenance=provenance,
        fully_articulated_path_answers=_query(source, described_object, config),
        index_answers=_query(
            source | indexes, described_object, config
        ),
        documented_answer_universe=_documented_answer_universe(source, config),
    )


def _term_id(term: Term) -> str:
    return term.value


def _answers_json(answers: dict[str, set[Term]]) -> str:
    return json.dumps(
        {family: sorted(_term_id(term) for term in values) for family, values in answers.items()},
        sort_keys=True,
        separators=(",", ":"),
    )


def _comparison_rows(results: list[RecordResult]) -> list[dict]:
    rows = []
    for result in results:
        recovered = result.index_recovered_answers
        rows.append(
            {
                "record_id": result.record_id,
                "described_object": result.described_object.value,
                "answers_fully_articulated_path_profile": _answers_json(
                    result.fully_articulated_path_answers
                ),
                "answers_index_profile": _answers_json(result.index_answers),
                "index_recovered_answers": _answers_json(recovered),
                "has_answer_set_gap": bool(any(recovered.values())),
                "index_recovered_e11_modification_count": len(
                    recovered["e11_modification"]
                ),
                "index_recovered_condition_count": len(recovered["condition"]),
                "index_recovered_material_count": len(recovered["material"]),
                "index_recovered_technique_count": len(recovered["technique"]),
            }
        )
    return rows


def _trace_sources(
    result: RecordResult, family: str, answer: Term, config: dict
) -> tuple[set[IndexEvidence], set[Triple]]:
    predicates = config["predicates"]
    if family == "e11_modification":
        triples = {
            Triple(
                result.described_object,
                predicates["index_modification"],
                answer,
            )
        }
    elif family == "condition":
        triples = {
            Triple(
                result.described_object,
                predicates["index_condition"],
                answer,
            )
        }
    else:
        property_predicate = (
            predicates["material"] if family == "material" else predicates["technique"]
        )
        events = {
            event
            for event in result.index_answers["e11_modification"]
            if answer in _objects(result.source, event, property_predicate)
        }
        triples = {
            Triple(
                result.described_object,
                predicates["index_modification"],
                event,
            )
            for event in events
        }
    triples &= result.index_triples
    evidence = {
        item
        for triple in triples
        for item in result.index_provenance.get(triple, set())
    }
    return evidence, triples


def _trace_rows(results: list[RecordResult], config: dict) -> list[dict]:
    rows = []
    for result in results:
        labels = _labels(result.source, config["predicates"]["label"])
        for family, answers in result.index_recovered_answers.items():
            for answer in sorted(answers):
                evidence, triples = _trace_sources(result, family, answer, config)
                if not evidence:
                    raise ValueError(
                        f"missing index provenance for {result.record_id} {family} {answer.value}"
                    )
                components = sorted({item.component for item in evidence})
                events = sorted({item.e11 for item in evidence})
                rows.append(
                    {
                        "record_id": result.record_id,
                        "query_family": family,
                        "index_recovered_answer_uri": answer.value,
                        "index_recovered_answer_label": labels.get(
                            answer, answer.value
                        ),
                        "source_component_uri": json.dumps([item.value for item in components]),
                        "source_component_label": json.dumps(
                            [labels.get(item, item.value) for item in components]
                        ),
                        "source_e11_uri": json.dumps([item.value for item in events]),
                        "source_e11_label": json.dumps(
                            [labels.get(item, item.value) for item in events]
                        ),
                        "source_component_p46_depth": json.dumps(
                            sorted({item.p46_depth for item in evidence})
                        ),
                        "minimum_p46_path_depth": min(
                            item.p46_depth for item in evidence
                        ),
                        "index_triple": json.dumps(
                            [_triple_text(triple) for triple in sorted(triples)]
                        ),
                        "index_rule_id": json.dumps(
                            sorted({item.rule_id for item in evidence})
                        ),
                    }
                )
    return rows


def _distribution_rows(results: list[RecordResult]) -> list[dict]:
    rows = []
    for result in results:
        for family, answers in result.index_recovered_answers.items():
            rows.append(
                {
                    "record_id": result.record_id,
                    "query_family": family,
                    "index_recovered_answer_count": len(answers),
                    "has_answer_set_gap": bool(answers),
                }
            )
    return rows


def _summary_rows(results: list[RecordResult]) -> list[dict]:
    totals_by_record = {
        result.record_id: sum(
            len(values) for values in result.index_recovered_answers.values()
        )
        for result in results
    }
    total_values = list(totals_by_record.values())
    changed = sum(value > 0 for value in total_values)
    aggregate = [
        ("total_records", len(results)),
        ("records_changed", changed),
        ("records_unchanged", len(results) - changed),
        (
            "total_index_recovered_e11_modifications",
            sum(
                len(result.index_recovered_answers["e11_modification"])
                for result in results
            ),
        ),
        (
            "total_index_recovered_conditions",
            sum(
                len(result.index_recovered_answers["condition"])
                for result in results
            ),
        ),
        (
            "total_index_recovered_materials",
            sum(
                len(result.index_recovered_answers["material"])
                for result in results
            ),
        ),
        (
            "total_index_recovered_techniques",
            sum(
                len(result.index_recovered_answers["technique"])
                for result in results
            ),
        ),
        ("mean_index_recovered_answers_per_record", statistics.mean(total_values)),
        ("median_index_recovered_answers_per_record", statistics.median(total_values)),
        ("max_index_recovered_answers_per_record", max(total_values, default=0)),
    ]
    rows = [
        {
            "section": "aggregate",
            "metric": metric,
            "value": value,
            "rank": "",
            "record_id": "",
            "index_recovered_answer_count": "",
        }
        for metric, value in aggregate
    ]
    top_records = sorted(totals_by_record.items(), key=lambda item: (-item[1], item[0]))[:10]
    rows.extend(
        {
            "section": "top_10_records",
            "metric": "index_recovered_answers",
            "value": count,
            "rank": rank,
            "record_id": record_id,
            "index_recovered_answer_count": count,
        }
        for rank, (record_id, count) in enumerate(top_records, start=1)
    )
    return rows


def _family_stats(results: list[RecordResult]) -> list[dict]:
    rows = []
    for family in ("e11_modification", "condition", "material", "technique"):
        counts = [
            len(result.index_recovered_answers[family])
            for result in results
        ]
        rows.append(
            {
                "query_family": family,
                "record_count": len(results),
                "records_changed": sum(count > 0 for count in counts),
                "records_unchanged": sum(count == 0 for count in counts),
                "total_index_recovered_answers": sum(counts),
                "mean_index_recovered_answers_per_record": statistics.mean(counts),
                "median_index_recovered_answers_per_record": statistics.median(counts),
                "max_index_recovered_answers_per_record": max(counts, default=0),
            }
        )
    return rows


def _record_recall_rows(results: list[RecordResult]) -> list[dict]:
    rows = []
    for result in results:
        for family in (
            "e11_modification",
            "condition",
            "material",
            "technique",
        ):
            articulated_count = len(
                result.fully_articulated_path_answers[family]
            )
            index_count = len(result.index_answers[family])
            recovered_count = len(result.index_recovered_answers[family])
            if articulated_count + recovered_count != index_count:
                raise ValueError(
                    f"index-profile answers are not a strict extension for "
                    f"{result.record_id} {family}"
                )
            rows.append(
                {
                    "record_id": result.record_id,
                    "query_family": family,
                    "fully_articulated_path_answer_count": articulated_count,
                    "index_profile_answer_count": index_count,
                    "index_recovered_answer_count": recovered_count,
                    "object_level_recall": (
                        articulated_count / index_count
                        if index_count
                        else ""
                    ),
                    "dark_record": (
                        articulated_count == 0 and index_count > 0
                    ),
                    "has_documented_index_path_answer": index_count > 0,
                }
            )
    return rows


def _corpus_recall_rows(
    record_recall_rows: list[dict], record_count: int
) -> list[dict]:
    rows = []
    for family in (
        "e11_modification",
        "condition",
        "material",
        "technique",
    ):
        family_rows = [
            row
            for row in record_recall_rows
            if row["query_family"] == family
        ]
        articulated = sum(
            int(row["fully_articulated_path_answer_count"])
            for row in family_rows
        )
        index_count = sum(
            int(row["index_profile_answer_count"])
            for row in family_rows
        )
        recovered = sum(
            int(row["index_recovered_answer_count"])
            for row in family_rows
        )
        eligible = sum(
            bool(row["has_documented_index_path_answer"])
            for row in family_rows
        )
        dark = sum(bool(row["dark_record"]) for row in family_rows)
        rows.append(
            {
                "query_family": family,
                "record_count": record_count,
                "fully_articulated_path_answer_count": articulated,
                "index_profile_answer_count": index_count,
                "index_recovered_answer_count": recovered,
                "object_level_recall": (
                    articulated / index_count if index_count else 1.0
                ),
                "dark_record_count": dark,
                "dark_record_rate_all_records": dark / record_count,
                "records_with_index_path_answers": eligible,
                "dark_record_rate_among_records_with_answers": (
                    dark / eligible if eligible else 0
                ),
            }
        )
    return rows


def _answer_space_rows(results: list[RecordResult]) -> list[dict]:
    rows = []
    for family in (
        "e11_modification",
        "condition",
        "material",
        "technique",
    ):
        visible = sum(
            len(result.fully_articulated_path_answers[family])
            for result in results
        )
        recovered = sum(
            len(result.index_recovered_answers[family])
            for result in results
        )
        residual = sum(
            len(
                result.documented_answer_universe[family]
                - result.index_answers[family]
            )
            for result in results
        )
        rows.append(
            {
                "query_family": family,
                "visible_in_fully_articulated_path_profile": visible,
                "index_recovered": recovered,
                "documented_but_outside_implemented_paths": residual,
                "documented_uri_level_answer_universe": (
                    visible + recovered + residual
                ),
                "counting_unit": "distinct URI per record and query family",
            }
        )
    return rows


def _eligible_index_answers(
    result: RecordResult, config: dict
) -> dict[str, set[Term]]:
    predicates = config["predicates"]
    modifications = _objects(
        result.index_triples,
        result.described_object,
        predicates["index_modification"],
    )
    return {
        "e11_modification": modifications,
        "condition": _objects(
            result.index_triples,
            result.described_object,
            predicates["index_condition"],
        ),
        "material": {
            value
            for event in modifications
            for value in _objects(result.source, event, predicates["material"])
        },
        "technique": {
            value
            for event in modifications
            for value in _objects(result.source, event, predicates["technique"])
        },
    }


def _unaffected_record_rows(
    results: list[RecordResult], config: dict
) -> list[dict]:
    rows = []
    for result in results:
        if any(result.index_recovered_answers.values()):
            continue
        eligible = _eligible_index_answers(result, config)
        fully_count = sum(
            len(values) for values in result.fully_articulated_path_answers.values()
        )
        index_count = sum(len(values) for values in result.index_answers.values())
        eligible_count = sum(len(values) for values in eligible.values())
        if eligible_count:
            category = "C_component_evidence_duplicates_object_visible_uris"
            explanation = (
                "Eligible component-path answers exist, but every indexed URI "
                "is already returned through a direct object-level CRM path."
            )
        elif index_count:
            category = "A_already_object_visible"
            explanation = (
                "The unchanged non-empty answer set is supplied by direct "
                "object-level CRM paths; no eligible index content exists."
            )
        else:
            category = "B_no_eligible_indexed_content"
            explanation = (
                "Both profiles return empty answer sets and no eligible "
                "component-path content exists for the declared index rules."
            )
        row = {
            "record_id": result.record_id,
            "classification": category,
            "classification_explanation": explanation,
            "fully_articulated_answer_count": fully_count,
            "index_profile_answer_count": index_count,
            "eligible_index_answer_count": eligible_count,
        }
        for family in (
            "e11_modification",
            "condition",
            "material",
            "technique",
        ):
            row[f"fully_articulated_{family}_count"] = len(
                result.fully_articulated_path_answers[family]
            )
            row[f"eligible_index_{family}_count"] = len(eligible[family])
        rows.append(row)
    return rows


def _unaffected_record_summary(rows: list[dict]) -> list[dict]:
    categories = (
        "A_already_object_visible",
        "B_no_eligible_indexed_content",
        "C_component_evidence_duplicates_object_visible_uris",
    )
    counts = Counter(row["classification"] for row in rows)
    return [
        {
            "classification": category,
            "record_count": counts[category],
            "share_of_unchanged_records": (
                counts[category] / len(rows) if rows else 0
            ),
        }
        for category in categories
    ]


def _condition_outside_path_rows(
    results: list[RecordResult], config: dict
) -> list[dict]:
    predicates = config["predicates"]
    rdf_type = predicates["rdf_type"]
    rows = []
    for result in results:
        graph = result.source
        labels = _labels(graph, predicates["label"])
        selected_depths = _p46_depths(
            graph, result.described_object, predicates["composition"]
        )
        selected_closure = set(selected_depths)
        e11 = _typed_subjects(
            graph, config["classes"]["modification"], rdf_type
        )
        e22 = _typed_subjects(
            graph, config["classes"]["described_object"], rdf_type
        )
        p46_objects = {
            triple.object
            for triple in graph
            if triple.predicate == predicates["composition"]
        }
        alternative_roots = e22 - selected_closure
        alternative_context = set()
        for root in alternative_roots:
            alternative_context.update(
                _p46_depths(graph, root, predicates["composition"])
            )
        residual = (
            result.documented_answer_universe["condition"]
            - result.index_answers["condition"]
        )
        for condition in sorted(residual):
            holders = _subjects(graph, predicates["condition"], condition)
            holder_events = {
                holder: (
                    _objects(graph, holder, predicates["modified_by"]) & e11
                )
                for holder in holders
            }
            if any(
                holder in selected_closure
                and holder != result.described_object
                and not holder_events[holder]
                for holder in holders
            ):
                category = "component_p44_without_typed_e11_p31i"
                explanation = (
                    "A holder is in the selected P46 closure but has no P31i "
                    "link to a typed E11 Modification, as required by the "
                    "condition index rule."
                )
            elif any(holder in alternative_context for holder in holders):
                category = "another_e22_object_context"
                explanation = (
                    "The condition belongs to a P46 closure rooted in another "
                    "E22 context rather than the selected described object."
                )
            elif any(
                holder in p46_objects and holder not in selected_closure
                for holder in holders
            ):
                category = "component_not_in_selected_p46_closure"
                explanation = (
                    "The P44 holder participates as a P46 component, but it is "
                    "not reachable from the selected described object."
                )
            else:
                category = "condition_attached_through_another_structure"
                explanation = (
                    "The P44 holder is not a component in the selected P46 "
                    "closure or another identified E22 context."
                )
            holder_types = {
                holder: sorted(
                    triple.object.value
                    for triple in graph
                    if triple.subject == holder
                    and triple.predicate == rdf_type
                    and triple.object.kind == "uri"
                )
                for holder in holders
            }
            rows.append(
                {
                    "record_id": result.record_id,
                    "condition_uri": condition.value,
                    "condition_label": labels.get(condition, condition.value),
                    "outside_path_category": category,
                    "category_explanation": explanation,
                    "p44_holder_uri": json.dumps(
                        [holder.value for holder in sorted(holders)]
                    ),
                    "p44_holder_label": json.dumps(
                        [labels.get(holder, holder.value) for holder in sorted(holders)]
                    ),
                    "p44_holder_types": json.dumps(
                        [holder_types[holder] for holder in sorted(holders)]
                    ),
                    "holder_in_selected_p46_closure": json.dumps(
                        [holder in selected_closure for holder in sorted(holders)]
                    ),
                    "holder_typed_e11_links": json.dumps(
                        [
                            sorted(event.value for event in holder_events[holder])
                            for holder in sorted(holders)
                        ]
                    ),
                }
            )
    return rows


def _condition_outside_path_summary(rows: list[dict]) -> list[dict]:
    categories = (
        "component_not_in_selected_p46_closure",
        "component_p44_without_typed_e11_p31i",
        "condition_attached_through_another_structure",
        "another_e22_object_context",
    )
    counts = Counter(row["outside_path_category"] for row in rows)
    return [
        {
            "outside_path_category": category,
            "condition_count": counts[category],
            "share_of_outside_conditions": (
                counts[category] / len(rows) if rows else 0
            ),
        }
        for category in categories
    ]


def _p46_depth_rows(trace_rows: list[dict]) -> list[dict]:
    counts = Counter(
        (
            row["query_family"],
            int(row["minimum_p46_path_depth"]),
        )
        for row in trace_rows
    )
    return [
        {
            "query_family": family,
            "minimum_p46_path_depth": depth,
            "index_recovered_answer_count": count,
        }
        for (family, depth), count in sorted(counts.items())
    ]


def _predicate_inventory(results: list[RecordResult], config: dict) -> list[dict]:
    crm_prefix = config["namespaces"]["crm"]
    included = {
        config["predicates"][key]
        for key in (
            "composition",
            "modified_by",
            "condition",
            "material",
            "technique",
        )
    }
    counts = Counter()
    record_counts = Counter()
    for result in results:
        seen = set()
        for triple in result.source:
            if triple.predicate.startswith(crm_prefix):
                counts[triple.predicate] += 1
                seen.add(triple.predicate)
        record_counts.update(seen)
    return [
        {
            "predicate_uri": predicate,
            "predicate_local_name": predicate[len(crm_prefix) :],
            "source_triple_count": counts[predicate],
            "record_count": record_counts[predicate],
            "evaluated": predicate in included,
            "scope_status": (
                "included competency-query path"
                if predicate in included
                else "present in source but outside this task-defined query scope"
            ),
        }
        for predicate in sorted(counts)
    ]


def _write_csv(
    path: Path, rows: list[dict], fieldnames: list[str] | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows and not fieldnames:
        raise ValueError(f"refusing to write headerless empty CSV: {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames or list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _escape_literal(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _nq_term(term: Term) -> str:
    if term.kind == "uri":
        return f"<{term.value}>"
    if term.kind == "bnode":
        return f"_:{term.value}"
    literal = f'"{_escape_literal(term.value)}"'
    if term.language:
        return f"{literal}@{term.language}"
    if term.datatype:
        return f"{literal}^^<{term.datatype}>"
    return literal


def _triple_text(triple: Triple) -> str:
    return f"{_nq_term(triple.subject)} <{triple.predicate}> {_nq_term(triple.object)}"


def _write_profiles(
    path: Path,
    results: list[RecordResult],
    config: dict,
    include_indexes: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    source_prefix = config["named_graphs"]["source_graph_prefix"]
    index_prefix = config["named_graphs"]["index_graph_prefix"]
    with path.open("w", encoding="utf-8") as handle:
        for result in results:
            source_graph = f"<{source_prefix}{quote(result.record_id, safe='')}>"
            for triple in sorted(result.source):
                handle.write(f"{_triple_text(triple)} {source_graph} .\n")
            if include_indexes:
                index_graph = f"<{index_prefix}{quote(result.record_id, safe='')}>"
                for triple in sorted(result.index_triples):
                    handle.write(
                        f"{_triple_text(triple)} {index_graph} .\n"
                    )


def _write_scope_note(path: Path, inventory: list[dict], config: dict) -> None:
    predicates = config["predicates"]
    excluded = [row for row in inventory if not row["evaluated"]]
    path.write_text(
        """# Scope Note

This experiment evaluates one task-defined object-level conservation query. It
does not test all CIDOC CRM paths or all information present in Ligatus.

## Included Paths

- `P46_is_composed_of+ / P31i_was_modified_by`: fully articulated path from
  the described object through one or more P46 components to E11 Modification.
- `P46_is_composed_of+ / P44_has_condition`: fully articulated path from the
  described object through one or more P46 components to condition state.
- `benchmark:indexModification`: custom E11 access index generated from the
  P46/P31i source path.
- `benchmark:indexCondition`: custom condition access index generated from the
  constrained P46/P31i/P44 source path.
- `P126_employed`: material reached from a directly visible or indexed E11.
- `P32_used_general_technique`: technique reached from a directly visible or
  indexed E11.

The configured predicate URIs are:

```json
"""
        + json.dumps(
            {
                key: predicates[key]
                for key in (
                    "composition",
                    "modified_by",
                    "condition",
                    "material",
                    "technique",
                    "index_modification",
                    "index_condition",
                )
            },
            indent=2,
            sort_keys=True,
        )
        + """
```

## Excluded Paths

All other CIDOC CRM predicates are outside the competency query, including
production, feature, temporal, type, measurement, attribution,
and activity-hierarchy paths. Their presence is inventoried rather than
interpreted. This keeps the comparison tied to the stated conservation task.

The source contains """
        + str(len(excluded))
        + """ other CRM predicates not evaluated here. See
`predicate_inventory.csv` for their URIs and corpus counts.

## Index Semantics

The index graph uses only the custom predicates `benchmark:indexModification`
and `benchmark:indexCondition`. It never generates CRM P31i or P44 assertions.
The index triples are retrieval metadata justified by fully articulated source
paths; they do not state that an E11 directly modified the described object or
that a component condition is literally a condition of the whole object.

The condition index rule is intentionally narrower than simple P46/P44
reachability. A component condition is indexed only when that same component
has a P31i link to a typed E11 Modification. This is a Ligatus task constraint
that limits the index to treatment-relevant component contexts. Conditions
excluded by this constraint are enumerated in
`condition_outside_path_diagnostic.csv` and summarized in
`condition_outside_path_summary.csv`.

## Deduplication

Answer comparison uses URI-level sets within each record and query family.
Labels are reported but never used to merge answers. When several source paths
support the same answer URI, the trace retains all supporting components, P46
depths, and E11 activities in JSON arrays. An index-recovered answer is the
URI-level set difference between the shortcut/index profile and the
fully-articulated-path profile for one record and query family.
""",
        encoding="utf-8",
    )


def _write_report(
    path: Path,
    results: list[RecordResult],
    family_rows: list[dict],
    recall_rows: list[dict],
    answer_space_rows: list[dict],
    condition_outside_summary: list[dict],
    unaffected_summary: list[dict],
) -> None:
    totals = {row["query_family"]: row for row in family_rows}
    recall = {row["query_family"]: row for row in recall_rows}
    answer_space = {row["query_family"]: row for row in answer_space_rows}
    changed = sum(
        any(result.index_recovered_answers.values()) for result in results
    )
    top = sorted(
        (
            (
                result.record_id,
                sum(
                    len(values)
                    for values in result.index_recovered_answers.values()
                ),
            )
            for result in results
        ),
        key=lambda item: (-item[1], item[0]),
    )[:10]
    lines = [
        "# Path-Index Answer-Set Comparison",
        "",
        "Index materialisation necessarily makes some fully articulated P46-path answers available to the shortcut/index query. That deterministic consequence is not treated as the empirical finding. The empirical result is the magnitude, distribution, object-level recall, and structural depth of the index-recovered URI-level answers in this corpus.",
        "",
        f"The shortcut/index profile changes object-level conservation retrieval in this Ligatus corpus: {changed} of {len(results)} records have an answer-set gap and {len(results) - changed} do not.",
        "",
        "| Query family | Records with gap | Index-recovered | Object-level recall | Dark records |",
        "|---|---:|---:|---:|---:|",
    ]
    for family in ("e11_modification", "condition", "material", "technique"):
        row = totals[family]
        recall_row = recall[family]
        lines.append(
            f"| {family} | {row['records_changed']} | "
            f"{row['total_index_recovered_answers']} | "
            f"{float(recall_row['object_level_recall']):.1%} | "
            f"{recall_row['dark_record_count']} |"
        )
    lines.extend(
        [
            "",
            "Object-level recall is the corpus-level count of URI answers from the fully-articulated-path profile divided by the count from the shortcut/index profile. Dark records have zero fully-articulated-path answers and at least one index-profile answer for the family.",
            "",
            "## Documented Answer Space",
            "",
            "| Query family | Directly visible | Index-recovered | Outside implemented paths | URI universe |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for family in ("e11_modification", "condition", "material", "technique"):
        row = answer_space[family]
        lines.append(
            f"| {family} | {row['visible_in_fully_articulated_path_profile']} | "
            f"{row['index_recovered']} | "
            f"{row['documented_but_outside_implemented_paths']} | "
            f"{row['documented_uri_level_answer_universe']} |"
        )
    lines.extend(
        [
            "",
            "Counts in this table are distinct URIs per record, not raw predicate-statement counts.",
            "",
            "## Top Records",
            "",
            "| Rank | Record | Index-recovered answers |",
            "|---:|---|---:|",
        ]
    )
    lines.extend(
        f"| {rank} | `{record_id}` | {count} |"
        for rank, (record_id, count) in enumerate(top, start=1)
    )
    lines.extend(
        [
            "",
            "## Conditions Outside the Index",
            "",
            "| Classification | Conditions | Share |",
            "|---|---:|---:|",
        ]
    )
    lines.extend(
        f"| {row['outside_path_category']} | {row['condition_count']} | "
        f"{float(row['share_of_outside_conditions']):.1%} |"
        for row in condition_outside_summary
    )
    lines.extend(
        [
            "",
            "## Unchanged Records",
            "",
            "| Classification | Records | Share of unchanged |",
            "|---|---:|---:|",
        ]
    )
    lines.extend(
        f"| {row['classification']} | {row['record_count']} | "
        f"{float(row['share_of_unchanged_records']):.1%} |"
        for row in unaffected_summary
    )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This result is limited to E11 modification, P44 condition, P126 material, and P32 technique retrieval through the configured P46 paths. It does not show that index profiles are generally better.",
            "",
            "The fully-articulated-path profile preserves the source structure. Object-level discovery requires either explicit custom access indexes or query services that traverse the fully articulated P46 paths. The generated index graph contains no synthetic CRM P31i or P44 assertions.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run(source_dir: Path, output_dir: Path, config_path: Path) -> list[RecordResult]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    paths = sorted(source_dir.glob(config["record_discovery_glob"]))
    if not paths:
        raise FileNotFoundError(
            f"no RDF/XML records matched {config['record_discovery_glob']} under {source_dir}"
        )
    results = [process_record(path, source_dir, config) for path in paths]
    comparison_rows = _comparison_rows(results)
    trace_rows = _trace_rows(results, config)
    summary_rows = _summary_rows(results)
    distribution_rows = _distribution_rows(results)
    family_rows = _family_stats(results)
    inventory_rows = _predicate_inventory(results, config)
    record_recall_rows = _record_recall_rows(results)
    recall_rows = _corpus_recall_rows(record_recall_rows, len(results))
    answer_space_rows = _answer_space_rows(results)
    depth_rows = _p46_depth_rows(trace_rows)
    condition_outside_rows = _condition_outside_path_rows(results, config)
    condition_outside_summary = _condition_outside_path_summary(
        condition_outside_rows
    )
    unaffected_rows = _unaffected_record_rows(results, config)
    unaffected_summary = _unaffected_record_summary(unaffected_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "path_profile_answer_set_comparison.csv",
        comparison_rows,
    )
    _write_csv(
        output_dir / "index_recovered_answer_trace.csv", trace_rows
    )
    _write_csv(
        output_dir / "index_recovery_summary_stats.csv", summary_rows
    )
    _write_csv(
        output_dir / "index_recovery_record_family_distribution.csv",
        distribution_rows,
    )
    _write_csv(
        output_dir / "index_recovery_family_stats.csv", family_rows
    )
    _write_csv(output_dir / "record_level_recall.csv", record_recall_rows)
    _write_csv(output_dir / "corpus_level_recall.csv", recall_rows)
    _write_csv(output_dir / "documented_answer_space.csv", answer_space_rows)
    _write_csv(output_dir / "p46_path_depth_distribution.csv", depth_rows)
    _write_csv(output_dir / "predicate_inventory.csv", inventory_rows)
    _write_csv(
        output_dir / "condition_outside_path_diagnostic.csv",
        condition_outside_rows,
        [
            "record_id",
            "condition_uri",
            "condition_label",
            "outside_path_category",
            "category_explanation",
            "p44_holder_uri",
            "p44_holder_label",
            "p44_holder_types",
            "holder_in_selected_p46_closure",
            "holder_typed_e11_links",
        ],
    )
    _write_csv(
        output_dir / "condition_outside_path_summary.csv",
        condition_outside_summary,
    )
    selection_summary_rows, selection_tie_rows = _described_object_selection_diagnostics(
        results, config
    )
    _write_csv(
        output_dir / "described_object_selection_summary.csv",
        selection_summary_rows,
        ["metric", "value"],
    )
    _write_csv(
        output_dir / "described_object_selection_ties.csv",
        selection_tie_rows,
        [
            "record_id",
            "candidate_uri",
            "closure_size",
            "has_P108i",
            "selected",
            "selection_reason",
        ],
    )
    _write_csv(
        output_dir / "unaffected_record_diagnostic.csv",
        unaffected_rows,
        [
            "record_id",
            "classification",
            "classification_explanation",
            "fully_articulated_answer_count",
            "index_profile_answer_count",
            "eligible_index_answer_count",
            "fully_articulated_e11_modification_count",
            "eligible_index_e11_modification_count",
            "fully_articulated_condition_count",
            "eligible_index_condition_count",
            "fully_articulated_material_count",
            "eligible_index_material_count",
            "fully_articulated_technique_count",
            "eligible_index_technique_count",
        ],
    )
    _write_csv(
        output_dir / "unaffected_record_summary.csv", unaffected_summary
    )
    _write_profiles(
        output_dir / "fully_articulated_path_profile.nq",
        results,
        config,
        include_indexes=False,
    )
    _write_profiles(
        output_dir / "index_profile.nq",
        results,
        config,
        include_indexes=True,
    )
    (output_dir / "index_rules.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_scope_note(output_dir / "scope_note.md", inventory_rows, config)
    _write_report(
        output_dir / "report.md",
        results,
        family_rows,
        recall_rows,
        answer_space_rows,
        condition_outside_summary,
        unaffected_summary,
    )
    return results


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Compare Ligatus fully-articulated-path and shortcut/index profiles."
        )
    )
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=root / "outputs")
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "config" / "index_rules.json",
    )
    args = parser.parse_args()
    results = run(args.source_dir, args.output_dir, args.config)
    config = json.loads(args.config.read_text(encoding="utf-8"))
    selection_summary_rows, _ = _described_object_selection_diagnostics(
        results, config
    )
    summary_values = {row["metric"]: int(row["value"]) for row in selection_summary_rows}
    print(
        f"Described-object selection: {summary_values['total_records']} records; "
        f"{summary_values['records_unambiguous_by_largest_closure']} unambiguous by largest P46 closure; "
        f"{summary_values['records_with_largest_closure_tie']} largest-closure ties; "
        f"{summary_values['ties_resolved_by_P108i']} resolved by P108i; "
        f"{summary_values['ties_resolved_by_lexical_uri']} resolved by lexical URI."
    )


if __name__ == "__main__":
    main()
