from pathlib import Path

import pytest

from remake_sensitivity.extraction import load_records
from remake_sensitivity.extraction_review import (
    evaluate_manual_review,
    reviewed_records,
    tier1_review_sensitivity,
)
from remake_sensitivity.stability import tier1_leave_one_out_auc


def test_manual_review_metrics_and_tier1_sensitivity_are_computable():
    records = load_records(
        Path("data/records"),
        [f"R{index:02d}" for index in range(1, 21)],
        Path("data/e11e81/extraction_vocabulary.yaml"),
    )
    rows, summary, expected = evaluate_manual_review(
        records, Path("data/e11e81/extraction_review.yaml")
    )
    assert summary["reviewed_record_count"] == 5
    assert summary["reviewed_event_count"] == len(rows)
    assert 0 <= summary["micro_precision"] <= 1
    assert 0 <= summary["micro_recall"] <= 1
    alternate = reviewed_records(records, expected)
    sensitivity = tier1_review_sensitivity(records, alternate, [0.0, 0.5, 1.0])
    assert [row["parameter_value"] for row in sensitivity] == [
        "0.00",
        "0.50",
        "1.00",
    ]


def test_leave_one_out_auc_has_full_and_one_row_per_eligible_record():
    # Minimal two-record, two-setting fixture.
    rows = [
        {
            "tier": "tier1",
            "parameter": parameter,
            "record_id": record_id,
            "eligible": True,
            "q1": q1,
            "q2": 1,
        }
        for parameter, values in (("0.00", (0, 0)), ("1.00", (1, 0)))
        for record_id, q1 in zip(("A", "B"), values)
    ]
    result = tier1_leave_one_out_auc(rows, run_id="run", dataset_id="toy")
    assert len(result) == 3
    full = next(row for row in result if row["is_full_sample"])
    assert full["direct_retrieval_recall_auc"] == pytest.approx(0.25)
