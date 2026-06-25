from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .extraction import Record
from .segmentation import segment_tier1


@dataclass(frozen=True)
class DateInterval:
    start: int | None
    end: int | None
    parser: str


def parse_date_interval(value: str) -> DateInterval | None:
    text = value.strip().lower()
    if not text or text in {
        "date not stated",
        "cataloguing history",
        "current catalogue state",
    }:
        return None
    years = [int(year) for year in re.findall(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)", text)]
    century = re.search(r"(\d{1,2})(?:st|nd|rd|th) century", text)
    if century:
        number = int(century.group(1))
        return DateInterval((number - 1) * 100, number * 100 - 1, "century")
    if text.startswith("before ") and years:
        return DateInterval(None, years[0] - 1, "before_year")
    if text.startswith(("after ", "since ")) and years:
        return DateInterval(years[0], None, "open_after_year")
    if text.startswith("by end of the ") and century:
        return DateInterval((int(century.group(1)) - 1) * 100, int(century.group(1)) * 100 - 1, "by_century_end")
    if len(years) >= 2:
        return DateInterval(min(years), max(years), "year_range_or_alternative")
    if len(years) == 1:
        return DateInterval(years[0], years[0], "year")
    return None


def event_order_audit(records: list[Record]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    record_rows: list[dict[str, Any]] = []
    inversion_rows: list[dict[str, Any]] = []
    for record in records:
        parsed = [
            (position, event, parse_date_interval(event.date))
            for position, event in enumerate(record.events, start=1)
        ]
        parseable = [(position, event, interval) for position, event, interval in parsed if interval]
        for left_index, (left_pos, left_event, left) in enumerate(parseable):
            assert left is not None
            for right_pos, right_event, right in parseable[left_index + 1 :]:
                assert right is not None
                if left.start is not None and right.end is not None and right.end < left.start:
                    inversion_rows.append(
                        {
                            "record_id": record.record_id,
                            "earlier_yaml_position": left_pos,
                            "earlier_event_id": left_event.event_id,
                            "earlier_date": left_event.date,
                            "later_yaml_position": right_pos,
                            "later_event_id": right_event.event_id,
                            "later_date": right_event.date,
                            "reason": f"later YAML event ends by {right.end}, before prior event starts at {left.start}",
                        }
                    )
        record_rows.append(
            {
                "record_id": record.record_id,
                "event_count": len(record.events),
                "parseable_date_count": len(parseable),
                "unparseable_date_count": len(record.events) - len(parseable),
                "has_parseable_date": bool(parseable),
                "inversion_count": sum(
                    row["record_id"] == record.record_id for row in inversion_rows
                ),
            }
        )
    return record_rows, inversion_rows


PREFERRED_MAKER_ROLES = {
    "maker",
    "original_maker",
    "musical_instrument_maker",
    "manufacturer",
    "attributed_maker",
}


def maker_link_audit(records: list[Record]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        data = yaml.safe_load(record.source_path.read_text(encoding="utf-8"))
        candidates = data.get("makers") or []
        candidate_text = " | ".join(
            f"{candidate.get('name', '')} [{candidate.get('role', '')}; "
            f"{candidate.get('epistemic_status', '')}]"
            for candidate in candidates
        )
        if record.maker:
            reason = "included: first non-unknown, non-anonymous candidate in an accepted maker role"
        elif not candidates:
            reason = "excluded: no maker candidates"
        elif all(
            str(candidate.get("name", "")).lower().startswith(("unknown", "anonymous"))
            or candidate.get("epistemic_status") == "unknown"
            for candidate in candidates
        ):
            reason = "excluded: candidates are unknown or anonymous"
        elif not any(candidate.get("role") in PREFERRED_MAKER_ROLES for candidate in candidates):
            reason = "excluded: no candidate has an accepted maker role"
        else:
            reason = "excluded: candidate failed name/status filter"
        rows.append(
            {
                "record_id": record.record_id,
                "maker_link_included": record.maker is not None,
                "selected_maker": record.maker or "",
                "decision_reason": reason,
                "source_candidates": candidate_text,
            }
        )
    return rows


def trailing_segment_audit(records: list[Record]) -> list[dict[str, Any]]:
    notes = {
        "R10": (
            "repeated_specific_and_generic_labels",
            "1972 restoration has only generic unspecified_fabric; the 1990 mechanism event repeats action, jacks, and strings. No clear missed label from the supplied wording.",
        ),
        "R12": (
            "repeated_specific_label",
            "Trailing removal of the coupling action repeats action; the wording supports the existing label and does not clearly imply a new atomic element.",
        ),
        "R16": (
            "repeated_specific_label",
            "Lost outer case repeats case. No clear missed label.",
        ),
        "R18": (
            "repeated_specific_labels; possible_missed_structure",
            "Keyboard, decoration, strings, and voicing all repeat earlier labels. Soundboard repair is mapped to decoration; structure is a plausible additional label and should be reviewed.",
        ),
        "R20": (
            "repeated_generic_label; source_underspecified",
            "All trailing restorations map to unspecified_fabric. The source descriptions name restorers but not the work, so missing specific labels are a documentation limitation rather than a detectable extraction error.",
        ),
    }
    rows = []
    for record in records:
        universe = set().union(*(set(event.elements) for event in record.events))
        if not universe:
            continue
        segments = segment_tier1(
            record.events, 1.0, total_elements=len(universe)
        )
        if len(segments) <= 1:
            continue
        trailing = segments[-1]
        prior_elements = set().union(
            *(set(event.elements) for segment in segments[:-1] for event in segment.events)
        )
        trailing_elements = set().union(*(set(event.elements) for event in trailing.events))
        classification, note = notes.get(
            record.record_id,
            (
                "requires_manual_review",
                "The record remains split at τ=1 and requires a manual trailing-event review.",
            ),
        )
        rows.append(
            {
                "record_id": record.record_id,
                "trailing_event_ids": "|".join(event.event_id for event in trailing.events),
                "trailing_dates": "|".join(event.date for event in trailing.events),
                "trailing_labels": "|".join(sorted(trailing_elements)),
                "repeated_labels": "|".join(sorted(trailing_elements & prior_elements)),
                "new_labels_after_boundary": "|".join(sorted(trailing_elements - prior_elements)),
                "zero_label_event_count": sum(not event.elements for event in trailing.events),
                "classification": classification,
                "audit_note": note,
            }
        )
    return rows
