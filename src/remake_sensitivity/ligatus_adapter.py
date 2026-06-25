from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from rdflib import Graph, RDF, RDFS, URIRef


CRM_BASE = "http://www.cidoc-crm.org/cidoc-crm/"


@dataclass(frozen=True)
class LigatusEvent:
    event_id: str
    label: str
    parent_event_id: str
    root_event_id: str
    episode_id: str
    episode_order: int
    episode_order_basis: str
    hierarchy_depth: int
    begin: str
    end: str
    root_begin: str
    root_end: str
    target_ids: tuple[str, ...]
    target_labels: tuple[str, ...]
    condition_ids: tuple[str, ...]
    condition_labels: tuple[str, ...]
    technique_ids: tuple[str, ...]
    technique_labels: tuple[str, ...]
    treatment_material_ids: tuple[str, ...]
    treatment_material_labels: tuple[str, ...]


@dataclass(frozen=True)
class LigatusRecord:
    record_id: str
    institution_code: str
    source_path: Path
    object_id: str
    object_label: str
    graph: Graph
    events: tuple[LigatusEvent, ...]
    episode_ids: tuple[str, ...]
    episode_labels: tuple[str, ...]
    ordering_policy_id: str
    ordering_rule_id: str
    ordering_rule_label: str
    ordering_action: str
    episode_order_basis: str
    source_root_count: int
    source_root_ids: tuple[str, ...]
    source_root_labels: tuple[str, ...]
    source_root_dates: tuple[str, ...]


@dataclass(frozen=True)
class EpisodeOrderingDecision:
    groups: tuple[tuple[str, tuple], ...]
    policy_id: str
    rule_id: str
    rule_label: str
    action: str


def _first_text(graph: Graph, subject, predicate) -> str:
    return str(next(graph.objects(subject, predicate), ""))


def _date_interval(graph: Graph, event, mapping: dict[str, URIRef]) -> tuple[str, str]:
    begins, ends = [], []
    for timespan in graph.objects(event, mapping["timespan"]):
        begins.extend(str(value) for value in graph.objects(timespan, mapping["begin"]))
        ends.extend(str(value) for value in graph.objects(timespan, mapping["end"]))
    return min(begins, default=""), max(ends, default="")


def _resolve_manifest_path(config_path: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    for parent in config_path.resolve().parents:
        resolved = parent / candidate
        if resolved.exists():
            return resolved
    raise FileNotFoundError(f"ordering policy manifest not found: {value}")


def load_ordering_manifest(config_path: Path) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    manifest_path = _resolve_manifest_path(
        config_path, config["ordering_policy_manifest"]
    )
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8"))


def _semantic_order(
    roots: set,
    labels: dict,
    rule: dict[str, Any],
) -> tuple | None:
    applies = rule["applies_when"]
    if len(roots) != int(applies["exact_root_count"]):
        return None
    ordered = []
    for cue in applies["ordered_label_cues"]:
        matches = [
            root for root in roots if cue.lower() in labels[root].lower()
        ]
        if len(matches) != 1:
            return None
        ordered.append(matches[0])
    if set(ordered) != roots:
        return None
    return tuple(ordered)


def _episode_groups(
    graph: Graph,
    roots: set,
    mapping: dict[str, URIRef],
    *,
    policy_id: str,
    ordering_manifest: dict[str, Any],
) -> EpisodeOrderingDecision:
    roots = set(roots)
    if len(roots) == 1:
        root = next(iter(roots))
        return EpisodeOrderingDecision(
            groups=((str(root), (root,)),),
            policy_id=policy_id,
            rule_id="single_source_root",
            rule_label="single source root",
            action="retain",
        )
    policy = ordering_manifest["policies"][policy_id]
    dates = {
        root: next(
            (
                value
                for value in _date_interval(graph, root, mapping)
                if value
            ),
            "",
        )
        for root in roots
    }
    if all(dates.values()) and policy["dated_roots_action"] == "split":
        ordered = sorted(roots, key=lambda root: (dates[root], str(root)))
        return EpisodeOrderingDecision(
            groups=tuple((str(root), (root,)) for root in ordered),
            policy_id=policy_id,
            rule_id="parsed_dates",
            rule_label="parsed dates",
            action="split",
        )
    labels = {
        root: _first_text(graph, root, RDFS.label) for root in roots
    }
    for rule_id in policy.get("semantic_rules", []):
        rule = ordering_manifest["semantic_rules"][rule_id]
        ordered = _semantic_order(roots, labels, rule)
        if ordered is not None:
            return EpisodeOrderingDecision(
                groups=tuple((str(root), (root,)) for root in ordered),
                policy_id=policy_id,
                rule_id=rule_id,
                rule_label=rule["label"],
                action=rule["action"],
            )
    ordered = tuple(sorted(roots, key=str))
    if policy["unsupported_undated_action"] == "split":
        return EpisodeOrderingDecision(
            groups=tuple((str(root), (root,)) for root in ordered),
            policy_id=policy_id,
            rule_id="all_roots_split",
            rule_label="all roots split",
            action="split",
        )
    episode_id = f"{ordered[0]}#grouped-unordered-roots"
    return EpisodeOrderingDecision(
        groups=((episode_id, ordered),),
        policy_id=policy_id,
        rule_id="no_supported_order",
        rule_label="no supported order",
        action="collapse",
    )


def _descendants_by_root(graph: Graph, modifications: set, parent_predicate):
    parent = {
        event: next(
            (
                candidate
                for candidate in graph.objects(event, parent_predicate)
                if candidate in modifications
            ),
            None,
        )
        for event in modifications
    }

    def root_and_depth(event):
        depth = 0
        current = event
        seen = set()
        while parent[current] is not None and current not in seen:
            seen.add(current)
            current = parent[current]
            depth += 1
        return current, depth

    return parent, {event: root_and_depth(event) for event in modifications}


def load_records(
    config_path: Path,
    data_dir: Path,
    *,
    order_policy: str | None = None,
) -> list[LigatusRecord]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    ordering_manifest = load_ordering_manifest(config_path)
    policy_id = order_policy or ordering_manifest["primary_policy"]
    if policy_id not in ordering_manifest["policies"]:
        raise ValueError(f"unknown Ligatus ordering policy: {policy_id}")
    mapping = {
        key: URIRef(value)
        for key, value in config["canonical_mapping"].items()
    }
    records = []
    for path in sorted(data_dir.glob("*/individual-records/*.rdf")):
        graph = Graph()
        graph.parse(path)
        objects = list(graph.subjects(RDF.type, mapping["object_class"]))
        primary = next(
            (
                obj
                for obj in objects
                if any(graph.objects(obj, mapping["production"]))
            ),
            objects[0],
        )
        modifications = set(
            graph.subjects(RDF.type, mapping["modification_class"])
        )
        parent, hierarchy = _descendants_by_root(
            graph, modifications, mapping["event_parent"]
        )
        roots = {root for root, _ in hierarchy.values()}
        decision = _episode_groups(
            graph,
            roots,
            mapping,
            policy_id=policy_id,
            ordering_manifest=ordering_manifest,
        )
        episode_groups = decision.groups
        root_episode = {
            str(root): (episode_id, index)
            for index, (episode_id, grouped_roots) in enumerate(
                episode_groups, start=1
            )
            for root in grouped_roots
        }
        root_dates = {
            str(root): _date_interval(graph, root, mapping)
            for root in roots
        }
        events = []
        for event in sorted(
            modifications,
            key=lambda item: (
                root_episode[str(hierarchy[item][0])][1],
                hierarchy[item][1],
                str(item),
            ),
        ):
            root, depth = hierarchy[event]
            targets = sorted(graph.subjects(mapping["modified_by"], event), key=str)
            conditions = sorted(
                {
                    condition
                    for target in targets
                    for condition in graph.objects(target, mapping["condition"])
                },
                key=str,
            )
            techniques = sorted(graph.objects(event, mapping["technique"]), key=str)
            materials = sorted(
                graph.objects(event, mapping["employed_material"]), key=str
            )
            begin, end = _date_interval(graph, event, mapping)
            root_begin, root_end = root_dates[str(root)]
            events.append(
                LigatusEvent(
                    event_id=str(event),
                    label=_first_text(graph, event, RDFS.label),
                    parent_event_id=str(parent[event] or ""),
                    root_event_id=str(root),
                    episode_id=root_episode[str(root)][0],
                    episode_order=root_episode[str(root)][1],
                    episode_order_basis=decision.rule_id,
                    hierarchy_depth=depth,
                    begin=begin,
                    end=end,
                    root_begin=root_begin,
                    root_end=root_end,
                    target_ids=tuple(map(str, targets)),
                    target_labels=tuple(
                        _first_text(graph, target, RDFS.label) for target in targets
                    ),
                    condition_ids=tuple(map(str, conditions)),
                    condition_labels=tuple(
                        _first_text(graph, condition, RDFS.label)
                        for condition in conditions
                    ),
                    technique_ids=tuple(map(str, techniques)),
                    technique_labels=tuple(
                        _first_text(graph, technique, RDFS.label)
                        for technique in techniques
                    ),
                    treatment_material_ids=tuple(map(str, materials)),
                    treatment_material_labels=tuple(
                        _first_text(graph, material, RDFS.label)
                        for material in materials
                    ),
                )
            )
        records.append(
            LigatusRecord(
                record_id=f"{path.parts[-3]}:{path.stem}",
                institution_code=path.parts[-3],
                source_path=path.relative_to(data_dir),
                object_id=str(primary),
                object_label=_first_text(graph, primary, RDFS.label),
                graph=graph,
                events=tuple(events),
                episode_ids=tuple(
                    episode_id for episode_id, _ in episode_groups
                ),
                episode_labels=tuple(
                    " + ".join(
                        _first_text(graph, root, RDFS.label)
                        for root in grouped_roots
                    )
                    for _, grouped_roots in episode_groups
                ),
                ordering_policy_id=decision.policy_id,
                ordering_rule_id=decision.rule_id,
                ordering_rule_label=decision.rule_label,
                ordering_action=decision.action,
                episode_order_basis=decision.rule_id,
                source_root_count=len(roots),
                source_root_ids=tuple(str(root) for root in sorted(roots, key=str)),
                source_root_labels=tuple(
                    _first_text(graph, root, RDFS.label)
                    for root in sorted(roots, key=str)
                ),
                source_root_dates=tuple(
                    "|".join(value for value in root_dates[str(root)] if value)
                    for root in sorted(roots, key=str)
                ),
            )
        )
    return records


def write_canonical_table(path: Path, records: list[LigatusRecord]) -> None:
    rows = [
        {
            "record_id": record.record_id,
            "institution_code": record.institution_code,
            "source_file": str(record.source_path),
            "object_id": record.object_id,
            "object_label": record.object_label,
            "event_id": event.event_id,
            "event_label": event.label,
            "parent_event_id": event.parent_event_id,
            "root_event_id": event.root_event_id,
            "episode_id": event.episode_id,
            "episode_order": event.episode_order,
            "episode_order_basis": event.episode_order_basis,
            "hierarchy_depth": event.hierarchy_depth,
            "begin": event.begin,
            "end": event.end,
            "root_begin": event.root_begin,
            "root_end": event.root_end,
            "target_ids": "|".join(event.target_ids),
            "target_labels": "|".join(event.target_labels),
            "condition_ids": "|".join(event.condition_ids),
            "condition_labels": "|".join(event.condition_labels),
            "technique_ids": "|".join(event.technique_ids),
            "technique_labels": "|".join(event.technique_labels),
            "treatment_material_ids": "|".join(event.treatment_material_ids),
            "treatment_material_labels": "|".join(
                event.treatment_material_labels
            ),
            "extraction_method": "structured_cidoc_crm",
        }
        for record in records
        for event in record.events
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
