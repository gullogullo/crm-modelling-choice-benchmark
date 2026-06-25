from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Iterable


@dataclass(frozen=True)
class Event:
    event_id: str
    label: str
    elements: frozenset[str] = field(default_factory=frozenset)
    date: str = ""
    agent: str = ""
    description: str = ""
    source_section: str = "historical_states"


@dataclass(frozen=True)
class Segment:
    index: int
    events: tuple[Event, ...]


def segment_tier0(events: Iterable[Event], k: int) -> list[Segment]:
    events = list(events)
    if k < 1:
        raise ValueError("k must be at least 1")
    return [
        Segment(index=i // k + 1, events=tuple(events[i : i + k]))
        for i in range(0, len(events), k)
    ]


def tier0_closed_form(event_count: int, k: int) -> int:
    if event_count < 1:
        return 0
    return ceil(event_count / k)


def segment_tier1(
    events: Iterable[Event],
    tau: float,
    *,
    total_elements: int | None = None,
    allow_zero_change_boundaries: bool = False,
) -> list[Segment]:
    """Segment after an event when its cumulative affected-element ratio reaches tau.

    A boundary after the final event would not create another populated segment, so
    it is intentionally omitted.
    """

    events = list(events)
    if not 0.0 <= tau <= 1.0:
        raise ValueError("tau must be between 0 and 1")
    if not events:
        return []

    # The denominator is fixed once from the record's entire documented history.
    # It must never be recomputed from a segment or from events seen so far.
    all_elements = set().union(*(set(event.elements) for event in events))
    denominator = len(all_elements) if total_elements is None else total_elements
    if denominator <= 0:
        return []

    segments: list[Segment] = []
    current: list[Event] = []
    cumulative: set[str] = set()

    for index, event in enumerate(events):
        current.append(event)
        newly_affected = set(event.elements) - cumulative
        cumulative.update(event.elements)
        changed_this_event = len(newly_affected) > 0
        ratio = len(cumulative) / denominator
        triggers = (
            (changed_this_event or allow_zero_change_boundaries)
            and ratio >= tau
            and index < len(events) - 1
        )
        if triggers:
            segments.append(Segment(index=len(segments) + 1, events=tuple(current)))
            current = []
            cumulative = set()

    if current:
        segments.append(Segment(index=len(segments) + 1, events=tuple(current)))
    return segments
