"""
report.py
-----------------------------------------------------------------------------
Runs every query in reports.sql against calls.db and prints a text report.

    python3 fetch_calls.py   # first, download the calls
    python3 report.py        # then print the report

Standard library only. Reads the database; never changes it.
-----------------------------------------------------------------------------
"""

import argparse
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "calls.db")
QUERIES_FILE = os.path.join(HERE, "reports.sql")


def load_queries(path=QUERIES_FILE):
    """Split reports.sql into (title, sql) pairs, using the "-- name:" lines."""
    queries = []
    title, lines = None, []
    with open(path) as f:
        for line in f:
            if line.startswith("-- name:"):
                if title:
                    queries.append((title, "".join(lines)))
                title, lines = line[len("-- name:"):].strip(), []
            elif title:
                lines.append(line)
    if title:
        queries.append((title, "".join(lines)))
    return queries


def format_value(value):
    """How one cell is printed: "-" for missing, at most 3 decimals for numbers."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")  # 7.0 -> "7", 0.150 -> "0.15"
    return str(value)


def format_table(headers, rows):
    """Turn rows into a simple text table with lined-up columns."""
    cells = [[format_value(v) for v in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) for i, h in enumerate(headers)]
    line = lambda values: "  ".join(v.ljust(w) for v, w in zip(values, widths)).rstrip()
    return "\n".join([line(headers), line(["-" * w for w in widths])] + [line(r) for r in cells])


def build_report(conn, queries=None):
    """Run each query and return the whole report as one string."""
    sections = []
    for title, sql in queries or load_queries():
        cursor = conn.execute(sql)
        headers = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        body = format_table(headers, rows) if rows else "(no data yet)"
        sections.append(f"{title}\n{'=' * len(title)}\n{body}")
    return "\n\n".join(sections)


def main():
    parser = argparse.ArgumentParser(description="Print the voice-agent monitoring report.")
    parser.add_argument("--db", default=DEFAULT_DB, help="database file (default calls.db)")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit("No calls.db yet. Run: python3 fetch_calls.py")

    # Open read-only ("mode=ro"), so the report can never change the data.
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    print(build_report(conn))


if __name__ == "__main__":
    main()
