from remake_sensitivity.metrics_normalized import calculate_normalized_metrics


def test_normalized_metric_calculation():
    result = calculate_normalized_metrics(
        eligible_record_count=5,
        segment_count=10,
        q1_count=2,
        q2_count=4,
    )
    assert result["identities_per_eligible_record"] == 2.0
    assert result["mean_excess_identity"] == 1.0
    assert result["direct_retrieval_recall"] == 0.5
    assert result["lineage_dependence_rate"] == 0.5
    assert result["q1_q2_gap_count"] == 2


def test_zero_q2_denominator_is_null_with_warning():
    result = calculate_normalized_metrics(
        eligible_record_count=5,
        segment_count=5,
        q1_count=0,
        q2_count=0,
    )
    assert result["direct_retrieval_recall"] is None
    assert result["lineage_dependence_rate"] is None
    assert "q2_count is zero" in result["metric_warnings"]
