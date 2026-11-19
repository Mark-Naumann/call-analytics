"""Tests that the sample calls are saved correctly, with no personal info."""

import re
import unittest

import fetch_calls
from tests.helpers import AGENT_NAMES, load_sample_calls, sample_database


def count(conn, sql):
    return conn.execute(sql).fetchone()[0]


class TestSaving(unittest.TestCase):
    def setUp(self):
        self.conn = sample_database()
        self.addCleanup(self.conn.close)  # close the database after each test

    def test_every_table_is_filled(self):
        self.assertEqual(count(self.conn, "SELECT COUNT(*) FROM agents"), 2)
        self.assertEqual(count(self.conn, "SELECT COUNT(*) FROM calls"), 4)
        self.assertEqual(count(self.conn, "SELECT COUNT(*) FROM messages"), 18)
        self.assertEqual(count(self.conn, "SELECT COUNT(*) FROM tool_calls"), 3)
        self.assertEqual(count(self.conn, "SELECT COUNT(*) FROM costs"), 8)
        self.assertEqual(count(self.conn, "SELECT COUNT(*) FROM quality_reviews"), 3)
        self.assertEqual(count(self.conn, "SELECT COUNT(*) FROM call_issues"), 4)

    def test_call_details(self):
        row = self.conn.execute(
            "SELECT duration_seconds, cost_usd, was_transferred FROM calls WHERE id = 'call-2'").fetchone()
        self.assertEqual(row, (60.0, 0.1, 1))

    def test_tool_calls_are_matched_with_results(self):
        rows = dict(self.conn.execute("SELECT id, is_error FROM tool_calls").fetchall())
        self.assertEqual(rows, {"tc-1": 0, "tc-2": 1, "tc-3": 1})  # tc-3 never got a result
        args = count(self.conn, "SELECT arguments FROM tool_calls WHERE id = 'tc-1'")
        self.assertEqual(args, '{"stop": "library"}')

    def test_quality_review_scores(self):
        scores = dict(self.conn.execute("SELECT call_id, overall_score FROM quality_reviews").fetchall())
        self.assertEqual(scores, {"call-1": 8.0, "call-2": 6.0, "call-3": 10.0})

    def test_field_names_are_tidied(self):
        # The sample has "best_callback_time\t" (a stray tab, like real Vapi data).
        fields = [r[0] for r in self.conn.execute("SELECT field FROM structured_outputs WHERE output_name = 'painting lead'")]
        self.assertIn("best_callback_time", fields)

    def test_running_twice_does_not_duplicate(self):
        fetch_calls.save_calls(self.conn, load_sample_calls(), AGENT_NAMES)
        self.assertEqual(count(self.conn, "SELECT COUNT(*) FROM calls"), 4)
        self.assertEqual(count(self.conn, "SELECT COUNT(*) FROM messages"), 18)
        self.assertEqual(count(self.conn, "SELECT COUNT(*) FROM call_issues"), 4)


class TestPrivacyInDatabase(unittest.TestCase):
    def test_no_personal_info_anywhere_in_the_database(self):
        conn = sample_database()
        self.addCleanup(conn.close)
        everything = []
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
            for row in conn.execute(f"SELECT * FROM {table}"):
                everything.extend(str(value) for value in row)
        text = "\n".join(everything)

        self.assertNotIn("should-never-be-saved", text)  # caller number + recording links
        self.assertNotIn("recording", text.lower())
        self.assertNotIn("Test Rider", text)             # personal structured-output fields
        self.assertNotIn("Test Caller", text)
        self.assertNotIn("1 Test Street", text)
        self.assertIsNone(re.search(r"\d{3}\D?\d{3}\D?\d{4}", text))  # nothing phone-shaped
        self.assertNotIn("@", text)                                   # no emails

    def test_personal_fields_show_as_redacted(self):
        conn = sample_database()
        self.addCleanup(conn.close)
        value = count(conn, "SELECT value FROM structured_outputs WHERE field = 'rider_name'")
        self.assertEqual(value, "<redacted>")


if __name__ == "__main__":
    unittest.main()
