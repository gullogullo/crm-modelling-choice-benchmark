from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .audits import parse_date_interval
from .extraction import _elements, _maker, load_extraction_vocabulary
from .segmentation import Event


@dataclass(frozen=True)
class CanonicalEvent:
    record_id: str
    event_id: str
    source_order: int
    parsed_date_interval: str
    event_label: str
    event_description: str
    event_kind: str
    affected_component_labels: frozenset[str]
    source_field: str
    source_reference: str
    extraction_method: str
    extraction_vocabulary_version: str
    date_text: str = ""
    agent: str = ""

    def as_segment_event(self) -> Event:
        return Event(
            event_id=self.event_id,
            label=self.event_label,
            elements=self.affected_component_labels,
            date=self.date_text,
            agent=self.agent,
            description=self.event_description,
            source_section=self.source_field,
        )


@dataclass(frozen=True)
class CanonicalRecord:
    record_id: str
    label: str
    maker: str | None
    classifications: tuple[str, ...]
    materials: tuple[str, ...]
    components: tuple[str, ...]
    source_references: tuple[str, ...]
    attribution_responsibility: tuple[str, ...]
    events: tuple[CanonicalEvent, ...]
    source_path: Path

    @property
    def total_elements(self) -> int:
        return len(
            set().union(
                *(set(event.affected_component_labels) for event in self.events)
            )
        )


def _interval_json(value: str) -> str:
    interval = parse_date_interval(value)
    if interval is None:
        return ""
    return json.dumps(
        {"start": interval.start, "end": interval.end, "parser": interval.parser},
        sort_keys=True,
    )


def _event_kind(
    state_type: str, description: str, rules: dict[str, Any]
) -> str:
    text = f"{state_type} {description}".lower()
    default_kind = "modification"
    for kind, rule in rules.items():
        if rule.get("default"):
            default_kind = kind
            continue
        if state_type in set(rule.get("state_type_terms", [])):
            return kind
        if any(term in text for term in rule.get("text_terms", [])):
            return kind
    return default_kind


def build_canonical_records(
    records_dir: Path,
    record_ids: list[str],
    *,
    vocabulary_path: Path,
    benchmark_config: dict[str, Any],
) -> list[CanonicalRecord]:
    vocabulary = load_extraction_vocabulary(vocabulary_path)
    rules = benchmark_config["canonical_events"]["event_kind_rules"]
    records = []
    for record_id in record_ids:
        path = records_dir / f"{record_id}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw_events = []
        for item in data.get("historical_states") or []:
            raw_events.append((item, "historical_states"))
        for item in data.get("restoration_events") or []:
            raw_events.append((item, "restoration_events"))
        if not raw_events:
            date = next(
                (
                    str(item.get("range_str", ""))
                    for item in data.get("dates") or []
                    if item.get("event_type") == "creation"
                ),
                "",
            )
            raw_events = [
                (
                    {
                        "state_type": "catalogued_creation",
                        "date": date,
                        "agent": _maker(data) or "UNKNOWN",
                        "description": (
                            "Synthetic creation event derived from the record's "
                            "maker/date fields."
                        ),
                        "source": "record_maker_and_date_fields",
                    },
                    "synthetic_creation",
                )
            ]
        events = []
        for source_order, (item, source_field) in enumerate(raw_events, start=1):
            state_type = str(item.get("state_type", "event"))
            description = str(item.get("description", ""))
            date_text = str(item.get("date", ""))
            events.append(
                CanonicalEvent(
                    record_id=record_id,
                    event_id=f"{record_id}_evt_{source_order:03d}",
                    source_order=source_order,
                    parsed_date_interval=_interval_json(date_text),
                    event_label=state_type,
                    event_description=description,
                    event_kind=_event_kind(state_type, description, rules),
                    affected_component_labels=_elements(
                        state_type, description, vocabulary
                    ),
                    source_field=source_field,
                    source_reference=str(item.get("source", "")),
                    extraction_method="deterministic_vocabulary",
                    extraction_vocabulary_version=str(vocabulary["version"]),
                    date_text=date_text,
                    agent=str(item.get("agent", "")),
                )
            )
        related = data.get("related_entities") or []
        materials = tuple(
            sorted(
                {
                    str(item["label"])
                    for item in related
                    if item.get("entity_type") == "material" and item.get("label")
                }
            )
        )
        components = tuple(
            sorted(
                {
                    str(item["label"])
                    for item in related
                    if item.get("entity_type") in {"component", "feature"}
                    and item.get("label")
                }
            )
        )
        classifications = tuple(
            dict.fromkeys(
                str(value)
                for value in (
                    data.get("instrument_type"),
                    data.get("category"),
                    data.get("label"),
                )
                if value
            )
        )
        source_references = tuple(
            sorted(
                {
                    str(item.get("id"))
                    for item in data.get("references") or []
                    if item.get("id")
                }
            )
        )
        attribution_responsibility = tuple(
            sorted(
                {
                    str(item["label"])
                    for item in related
                    if item.get("relation")
                    in {"authenticator", "attributor", "cataloguer"}
                    and item.get("label")
                }
            )
        )
        records.append(
            CanonicalRecord(
                record_id=record_id,
                label=str(data.get("label", record_id)),
                maker=_maker(data),
                classifications=classifications,
                materials=materials,
                components=components,
                source_references=source_references,
                attribution_responsibility=attribution_responsibility,
                events=tuple(events),
                source_path=path,
            )
        )
    return records


def canonical_event_rows(records: list[CanonicalRecord]) -> list[dict[str, Any]]:
    return [
        {
            "record_id": event.record_id,
            "event_id": event.event_id,
            "source_order": event.source_order,
            "parsed_date_interval": event.parsed_date_interval,
            "event_label": event.event_label,
            "event_description": event.event_description,
            "event_kind": event.event_kind,
            "affected_component_labels": "|".join(
                sorted(event.affected_component_labels)
            ),
            "source_field": event.source_field,
            "source_reference": event.source_reference,
            "extraction_method": event.extraction_method,
            "extraction_vocabulary_version": event.extraction_vocabulary_version,
        }
        for record in records
        for event in record.events
    ]


def write_canonical_event_table(
    path: Path, records: list[CanonicalRecord]
) -> None:
    rows = canonical_event_rows(records)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
