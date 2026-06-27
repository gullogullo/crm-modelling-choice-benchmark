import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ligatus_object_scope import (
    _condition_outside_path_rows,
    _unaffected_record_rows,
    process_record,
    run,
)


class PathProfileExperimentTest(unittest.TestCase):
    def setUp(self):
        self.config_path = ROOT / "config" / "index_rules.json"
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.fixture = ROOT / "tests" / "fixtures" / "example.rdf"
        self.duplicate_fixture = ROOT / "tests" / "fixtures" / "duplicate.rdf"

    def test_profiles_preserve_source_and_add_expected_answers(self):
        result = process_record(self.fixture, self.fixture.parent, self.config)
        self.assertEqual(
            result.fully_articulated_path_answers["e11_modification"], set()
        )
        self.assertEqual(
            {term.value for term in result.index_answers["e11_modification"]},
            {"http://example.org/treatment"},
        )
        self.assertEqual(
            {
                term.value
                for term in result.index_recovered_answers["condition"]
            },
            {"http://example.org/detached"},
        )
        self.assertEqual(
            {
                term.value
                for term in result.index_recovered_answers["material"]
            },
            {"http://example.org/paper"},
        )
        self.assertEqual(
            {
                term.value
                for term in result.index_recovered_answers["technique"]
            },
            {"http://example.org/pasting"},
        )
        self.assertTrue(result.index_triples.isdisjoint(result.source))
        self.assertEqual(
            {triple.predicate for triple in result.index_triples},
            {
                self.config["predicates"]["index_modification"],
                self.config["predicates"]["index_condition"],
            },
        )
        self.assertFalse(
            any(
                triple.subject == result.described_object
                and triple.predicate
                in {
                    self.config["predicates"]["modified_by"],
                    self.config["predicates"]["condition"],
                }
                for triple in result.index_triples
            )
        )
        outside = _condition_outside_path_rows([result], self.config)
        self.assertEqual(len(outside), 1)
        self.assertEqual(
            outside[0]["outside_path_category"],
            "component_p44_without_typed_e11_p31i",
        )

    def test_duplicate_component_answer_is_classified_as_unchanged(self):
        result = process_record(
            self.duplicate_fixture,
            self.duplicate_fixture.parent,
            self.config,
        )
        self.assertFalse(any(result.index_recovered_answers.values()))
        diagnostic = _unaffected_record_rows([result], self.config)
        self.assertEqual(len(diagnostic), 1)
        self.assertEqual(
            diagnostic[0]["classification"],
            "C_component_evidence_duplicates_object_visible_uris",
        )

    def test_outputs_have_one_trace_row_per_index_recovered_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "x" / "individual-records"
            source.mkdir(parents=True)
            (source / "example.rdf").write_bytes(self.fixture.read_bytes())
            output = Path(temporary) / "outputs"
            results = run(Path(temporary), output, self.config_path)
            self.assertEqual(len(results), 1)
            trace_lines = (output / "index_recovered_answer_trace.csv").read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(len(trace_lines), 5)
            index_graph = (output / "index_profile.nq").read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "urn:ligatus-object-scope:index", index_graph
            )
            self.assertIn("indexModification", index_graph)
            self.assertIn("indexCondition", index_graph)
            report = (output / "report.md").read_text(encoding="utf-8")
            self.assertIn(
                "The shortcut/index profile changes object-level conservation retrieval",
                report,
            )
            self.assertIn(
                "contains no synthetic CRM P31i or P44 assertions",
                report,
            )


if __name__ == "__main__":
    unittest.main()
