from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .segmentation import Event


DEFAULT_VOCABULARY_PATH = Path("data/e11e81/extraction_vocabulary.yaml")


@dataclass(frozen=True)
class Record:
    record_id: str
    label: str
    maker: str | None
    events: tuple[Event, ...]
    source_path: Path

    @property
    def total_elements(self) -> int:
        return len(set().union(*(set(event.elements) for event in self.events)))


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def load_extraction_vocabulary(path: Path | None = None) -> dict[str, Any]:
    vocabulary_path = path or DEFAULT_VOCABULARY_PATH
    return yaml.safe_load(vocabulary_path.read_text(encoding="utf-8"))


def _elements(
    state_type: str,
    description: str,
    vocabulary: dict[str, Any],
) -> frozenset[str]:
    text = f"{state_type} {description}".lower()
    found = {
        element
        for element, needles in vocabulary["labels"].items()
        if any(needle in text for needle in needles)
    }
    if (
        state_type in set(vocabulary["creation_state_types"])
        or "original" in state_type
        and "construction" in text
    ):
        found.add(vocabulary["creation_label"])
    if not found and any(
        token in text
        for token in vocabulary["generic_change_terms"]
    ):
        found.add(vocabulary["generic_change_label"])
    return frozenset(sorted(found))


def _maker(data: dict[str, Any]) -> str | None:
    preferred_roles = {
        "maker",
        "original_maker",
        "musical_instrument_maker",
        "manufacturer",
        "attributed_maker",
    }
    makers = data.get("makers") or []
    for maker in makers:
        name = _text(maker.get("name")).strip()
        if (
            maker.get("role") in preferred_roles
            and maker.get("epistemic_status") != "unknown"
            and name
            and not name.lower().startswith(("unknown", "anonymous"))
        ):
            return name
    return None


def _creation_fallback(data: dict[str, Any]) -> dict[str, Any]:
    date = ""
    for item in data.get("dates") or []:
        if item.get("event_type") == "creation":
            date = _text(item.get("range_str"))
            break
    return {
        "state_type": "catalogued_creation",
        "date": date,
        "agent": _maker(data) or "UNKNOWN",
        "description": "Synthetic creation event derived from the record's maker/date fields.",
        "_source_section": "synthetic_creation",
    }


def load_records(
    records_dir: Path,
    record_ids: list[str],
    extraction_vocabulary_path: Path | None = None,
) -> list[Record]:
    vocabulary = load_extraction_vocabulary(extraction_vocabulary_path)
    records: list[Record] = []
    for record_id in record_ids:
        path = records_dir / f"{record_id}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw_events: list[dict[str, Any]] = []
        for item in data.get("historical_states") or []:
            raw_events.append({**item, "_source_section": "historical_states"})
        for item in data.get("restoration_events") or []:
            raw_events.append(
                {
                    **item,
                    "state_type": item.get("state_type", "restoration"),
                    "_source_section": "restoration_events",
                }
            )
        if not raw_events:
            raw_events = [_creation_fallback(data)]

        events = []
        for position, item in enumerate(raw_events, start=1):
            state_type = _text(item.get("state_type") or "event")
            description = _text(item.get("description"))
            events.append(
                Event(
                    event_id=f"{record_id}_evt_{position:03d}",
                    label=state_type,
                    elements=_elements(state_type, description, vocabulary),
                    date=_text(item.get("date")),
                    agent=_text(item.get("agent")),
                    description=description,
                    source_section=_text(item.get("_source_section")),
                )
            )
        records.append(
            Record(
                record_id=record_id,
                label=_text(data.get("label")),
                maker=_maker(data),
                events=tuple(events),
                source_path=path,
            )
        )
    return records


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "unknown"
