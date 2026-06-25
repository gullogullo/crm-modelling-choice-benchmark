import csv
import json
from pathlib import Path

from remake_sensitivity.reconcile import reconcile_runs


def _write_run(root: Path, run_id: str, q1: float) -> None:
    results = root / "results"
    results.mkdir(parents=True)
    (results / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "input_data_hash": "input",
                "config_hash": "config",
                "code_hash": "code",
            }
        ),
        encoding="utf-8",
    )
    with (results / "normalized_metrics_by_parameter.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "tier",
                "parameter_value",
                "convention",
                "segment_count",
                "q1_count",
                "q2_count",
                "identities_per_eligible_record",
                "mean_excess_identity",
                "direct_retrieval_recall",
                "lineage_dependence_rate",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "tier": "toy",
                "parameter_value": "0",
                "convention": "",
                "segment_count": 2,
                "q1_count": q1,
                "q2_count": 2,
                "identities_per_eligible_record": 2,
                "mean_excess_identity": 1,
                "direct_retrieval_recall": q1 / 2,
                "lineage_dependence_rate": 1 - q1 / 2,
            }
        )


def test_reconciliation_reports_changed_metric(tmp_path):
    current = tmp_path / "current"
    previous = tmp_path / "previous"
    _write_run(current, "current", 1)
    _write_run(previous, "previous", 0)
    rows = reconcile_runs(current, previous)
    q1 = next(row for row in rows if row["metric_id"] == "q1_count")
    assert q1["status"] == "changed"
    assert q1["absolute_delta"] == 1
