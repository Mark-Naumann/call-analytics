"""Tests that every query in reports.sql gives the right answer for the sample calls.

The expected numbers were worked out by hand from tests/sample_calls.json:
  Jordan: call-1 (2 min, $0.20, two silent gaps of 4.5 s), call-2 (1 min, $0.10, transferred,
          one tool error + one tool call with no result). Reviews scored 8 and 6.
  Sam:    call-3 (3 min, $0.30, review scored 10), call-4 (4 min, $0.40, no review).
"""

import sqlite3
import unittest

import report
from tests.helpers import sample_database


def run(conn, title):
    """Run one named query from reports.sql; return its rows as dicts."""
    sql = dict(report.load_queries())[title]
    cursor = conn.execute(sql)
    headers = [c[0] for c in cursor.description]
    return [dict(zip(headers, row)) for row in cursor.fetchall()]


def by_agent(rows):
    return {row["agent"]: row for row in rows}


class TestReports(unittest.TestCase):
    def setUp(self):
        self.conn = sample_database()
        self.addCleanup(self.conn.close)  # close the database after each test
        self.jordan, self.sam = "Jordan - Test Transit", "Sam - Test Painting"

    def test_all_eight_reports_exist(self):
        titles = [title for title, _ in report.load_queries()]
        self.assertEqual(len(titles), 8)
        self.assertIn("Dead air (gaps over 3 seconds between turns)", titles)

    def test_calls_per_agent(self):
        rows = by_agent(run(self.conn, "Calls per agent"))
        self.assertEqual(rows[self.jordan]["calls"], 2)
        self.assertEqual(rows[self.sam]["calls"], 2)

    def test_average_quality_score(self):
        rows = by_agent(run(self.conn, "Average quality score"))
        self.assertEqual(rows[self.jordan]["avg_score"], 7.0)    # (8 + 6) / 2
        self.assertEqual(rows[self.jordan]["goal_met_pct"], 50.0)
        self.assertEqual(rows[self.sam]["avg_score"], 10.0)      # only call-3 was reviewed
        self.assertEqual(rows[self.sam]["reviewed_calls"], 1)

    def test_transfer_rate(self):
        rows = by_agent(run(self.conn, "Transfer rate"))
        self.assertEqual(rows[self.jordan]["transfer_rate_pct"], 50.0)
        self.assertEqual(rows[self.sam]["transfer_rate_pct"], 0.0)

    def test_tool_error_rate(self):
        [row] = run(self.conn, "Tool error rate")
        self.assertEqual((row["tool_name"], row["tool_calls"], row["errors"], row["error_rate_pct"]),
                         ("get_next_bus", 3, 2, 66.7))

    def test_dead_air(self):
        rows = by_agent(run(self.conn, "Dead air (gaps over 3 seconds between turns)"))
        jordan = rows[self.jordan]
        self.assertEqual(jordan["gaps_over_3s"], 2)
        self.assertEqual(jordan["agent_slow"], 1)      # 4.5 s before Jordan answered
        self.assertEqual(jordan["caller_quiet"], 1)    # 4.5 s before the caller spoke
        self.assertEqual(jordan["calls_affected"], 1)
        self.assertEqual(jordan["longest_gap_s"], 4.5)
        self.assertEqual(rows[self.sam]["gaps_over_3s"], 0)

    def test_average_call_length_and_cost(self):
        rows = by_agent(run(self.conn, "Average call length and cost"))
        self.assertEqual(rows[self.jordan]["avg_minutes"], 1.5)
        self.assertEqual(rows[self.jordan]["avg_cost_usd"], 0.15)
        self.assertEqual(rows[self.sam]["total_cost_usd"], 0.7)
        self.assertEqual(rows[self.sam]["cost_per_minute_usd"], 0.1)   # $0.70 / 7 minutes

    def test_where_the_money_goes(self):
        rows = {r["cost_type"]: r for r in run(self.conn, "Where the money goes")}
        self.assertEqual(rows["voice"]["total_usd"], 0.76)
        self.assertEqual(rows["voice"]["share_pct"], 76.0)

    def test_most_common_issues(self):
        rows = run(self.conn, "Most common issues found")
        self.assertEqual(rows[0], {"issue": "asked two questions at once", "times_found": 2, "calls": 2})
        self.assertEqual({r["issue"] for r in rows},
                         {"asked two questions at once", "long pause before answering", "tool error"})


class TestPrintedReport(unittest.TestCase):
    def test_report_has_every_section(self):
        conn = sample_database()
        self.addCleanup(conn.close)
        text = report.build_report(conn)
        for title, _ in report.load_queries():
            self.assertIn(title, text)
        self.assertIn("get_next_bus", text)

    def test_empty_database_says_no_data_yet(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        with open("schema.sql") as f:
            conn.executescript(f.read())
        self.assertIn("(no data yet)", report.build_report(conn))

    def test_numbers_are_printed_simply(self):
        self.assertEqual(report.format_value(7.0), "7")
        self.assertEqual(report.format_value(0.150), "0.15")
        self.assertEqual(report.format_value(None), "-")


if __name__ == "__main__":
    unittest.main()
