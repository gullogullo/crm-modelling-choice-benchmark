from __future__ import annotations

METRIC_SCHEMA_VERSION = "1.0"
INTEGRATION_METHOD = "weighted_trapezoidal_over_normalized_parameter_grid"

NORMALIZED_METRIC_DEFINITIONS = {
    "identities_per_eligible_record": (
        "Represented object identities divided by eligible source records."
    ),
    "mean_excess_identity": (
        "Average number of additional represented object identities per eligible "
        "source record."
    ),
    "direct_retrieval_recall": (
        "Share of lineage-reachable maker-linked current objects also retrievable "
        "through direct current-object production."
    ),
    "lineage_dependence_rate": (
        "Share of lineage-reachable maker-linked current objects requiring lineage "
        "traversal rather than direct current-object production."
    ),
}

AUC_METRICS = tuple(NORMALIZED_METRIC_DEFINITIONS)
