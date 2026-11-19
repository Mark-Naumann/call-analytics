"""Shared helpers for the tests: load the made-up sample calls into a database."""

import json
import os
import sqlite3

import fetch_calls

SAMPLE_FILE = os.path.join(os.path.dirname(__file__), "sample_calls.json")
AGENT_NAMES = {"asst-jordan": "Jordan - Test Transit", "asst-sam": "Sam - Test Painting"}


def load_sample_calls():
    with open(SAMPLE_FILE) as f:
        return json.load(f)


def sample_database():
    """A brand-new in-memory database (nothing written to disk) with the sample calls."""
    conn = sqlite3.connect(":memory:")
    with open(os.path.join(os.path.dirname(fetch_calls.__file__), "schema.sql")) as f:
        conn.executescript(f.read())
    fetch_calls.save_calls(conn, load_sample_calls(), AGENT_NAMES)
    return conn
