from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyse_outputs import (
    family_statistics,
    normalize_component_label,
    record_distribution,
)


class DistributionAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "record_id": "x:a",
                "index_recovered_e11_modification_count": "2",
                "index_recovered_condition_count": "1",
                "index_recovered_material_count": "0",
                "index_recovered_technique_count": "3",
            },
            {
                "record_id": "x:b",
                "index_recovered_e11_modification_count": "0",
                "index_recovered_condition_count": "1",
                "index_recovered_material_count": "4",
                "index_recovered_technique_count": "0",
            },
        ]

    def test_family_statistics_use_affected_record_denominator(self):
        stats = {row["query_family"]: row for row in family_statistics(self.rows)}
        self.assertEqual(stats["e11_modification"]["records_affected"], 1)
        self.assertEqual(stats["e11_modification"]["mean_per_affected_record"], 2)
        self.assertEqual(stats["condition"]["records_affected"], 2)
        self.assertEqual(stats["condition"]["mean_per_affected_record"], 1)

    def test_record_totals_are_family_sums(self):
        distribution = {row["record_id"]: row for row in record_distribution(self.rows)}
        self.assertEqual(
            distribution["x:a"]["total_index_recovered_answers"], 6
        )
        self.assertEqual(
            distribution["x:b"]["total_index_recovered_answers"], 5
        )

    def test_component_normalization_removes_only_record_context(self):
        self.assertEqual(
            normalize_component_label("  Left Board (Bodleian, R01) "),
            "left board",
        )
        self.assertEqual(normalize_component_label("Board"), "board")


if __name__ == "__main__":
    unittest.main()
