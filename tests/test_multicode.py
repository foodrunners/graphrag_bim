"""Acceptance checks for the two shared design questions in this pilot."""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_tools"))
from multicode import read_graph, trace


class CrossCodeReviewTests(unittest.TestCase):
    def setUp(self):
        self.graph = read_graph()
        self.records, self.labels, _, self.edges = self.graph

    def test_washroom_returns_two_alarm_functions_and_their_sources(self):
        keys, lines = trace("washroom", self.graph)
        records = [self.records[key] for key in keys]
        systems = {e["to_id"] for e in self.edges if e["from_id"] in keys and e["relation"] == "concerns_system"}
        self.assertEqual(systems, {"system:assistance-alarm", "system:fire-alarm"})
        self.assertEqual({r["authority"] for r in records}, {"BCA", "SCDF"})
        fire = next(r for r in records if r["authority"] == "SCDF")
        self.assertIn("building protected by a fire alarm system", fire["applies_when"])
        self.assertIn("5.8.4.2", {r["code_ref"] for r in records})
        self.assertTrue(any("acceptable_solution_for" in line for line in lines))
        self.assertFalse(any(e["relation"] == "same_as" for e in self.edges))

    def test_ramp_names_a_document_and_finds_a_conditioned_clause(self):
        keys, _ = trace("ramp", self.graph)
        fire = next(key for key in keys if self.records[key]["authority"] == "SCDF")
        explicit = [e for e in self.edges if e["from_id"] == fire and e["basis"] == "explicit_citation"]
        self.assertEqual([e["to_id"] for e in explicit], ["doc:accessibility-code"])
        self.assertNotIn("2025", self.labels["doc:accessibility-code"])
        refs = {self.records[key]["code_ref"] for key in keys}
        self.assertIn("4.6.2.1", refs)
        self.assertIn("Table 4", refs)
        self.assertNotIn("5.8.4", refs)

    def test_current_sources_resolve_at_their_published_granularity(self):
        for row in self.records.values():
            self.assertTrue(row["source_id"] and row["applies_when"] and row["source_url"].startswith("https://"))
            if row["authority"] == "SCDF":
                self.assertTrue(row["source_locator"].startswith("HTML clause"))
            else:
                self.assertIn("#page=", row["source_url"])


if __name__ == "__main__":
    unittest.main()
