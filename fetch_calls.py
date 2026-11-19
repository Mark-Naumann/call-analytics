"""
fetch_calls.py
-----------------------------------------------------------------------------
Downloads my recent Vapi calls and saves them into a SQLite database (calls.db).

    python3 fetch_calls.py              # last 14 days
    python3 fetch_calls.py --days 7     # last 7 days

READ-ONLY: it only ever sends GET requests to Vapi (see vapi_get below), so it
cannot change any agent, call or setting.

PRIVACY: before anything is saved, it drops caller phone numbers and recording
links, masks phone numbers and emails inside text, and hides personal fields
(names, numbers, addresses, IDs) from structured outputs.

Needs: a .env file with VAPI_API_KEY=<your Vapi private key>. Python 3.10+,
standard library only (nothing to install).
-----------------------------------------------------------------------------
"""

import argparse
import json
import os
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

API = "https://api.vapi.ai"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(HERE, "calls.db")
QUALITY_REVIEW = "call quality review"  # name of the QA structured output in Vapi
PAGE_SIZE = 100  # Vapi returns at most 100 calls per request
# My Vapi plan keeps 14 days of call history; asking for older calls is refused.
DEFAULT_DAYS = 14


# =============================================================================
# 1. The API key (from .env, never printed)
# =============================================================================

def load_api_key():
    """Read VAPI_API_KEY from the .env file next to this script."""
    env_file = os.path.join(HERE, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                name, _, value = line.strip().partition("=")
                if name.strip() == "VAPI_API_KEY":
                    return value.strip().strip("\"'")
    return os.environ.get("VAPI_API_KEY")


# =============================================================================
# 2. Talking to Vapi: GET requests ONLY
# =============================================================================

def vapi_get(path, params=None, api_key=None):
    """The ONLY function that contacts Vapi. It can only read (GET).

    Example: vapi_get("/call", {"limit": 100}) -> list of calls.
    """
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {api_key}",  # sent to Vapi, never printed
            # Vapi's firewall blocks Python's default name, so we send our own.
            "User-Agent": "call-analytics/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def fetch_recent_calls(api_key, days=DEFAULT_DAYS):
    """Download every call from the last `days` days, 100 at a time.

    Vapi returns one "page" of up to 100 calls. To get the next page we ask for
    calls created before the oldest one we already have, until a page comes
    back with fewer than 100 (that means we reached the end).
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    calls = []
    before = None
    while True:
        params = {"limit": PAGE_SIZE, "createdAtGt": since}
        if before:
            params["createdAtLt"] = before
        page = vapi_get("/call", params, api_key)
        calls.extend(page)
        if len(page) < PAGE_SIZE:
            return calls
        before = min(call["createdAt"] for call in page)


def find_agent_names(calls, api_key):
    """Map each assistant ID to its name, e.g. {"8c2b...": "Jordan - Transit"}.

    The name is usually inside the call already (on the agent's messages).
    Only if it isn't do we look the assistant up (another GET request).
    """
    names = {}
    for call in calls:
        agent_id = call.get("assistantId")
        for message in messages_of(call):
            if agent_id and agent_id not in names and message.get("assistantName"):
                names[agent_id] = message["assistantName"]
    for agent_id in {call.get("assistantId") for call in calls} - set(names) - {None}:
        try:
            names[agent_id] = vapi_get(f"/assistant/{agent_id}", api_key=api_key).get("name", agent_id)
        except urllib.error.HTTPError:
            names[agent_id] = agent_id  # e.g. the assistant was deleted
    return names


# =============================================================================
# 3. Privacy: remove personal info before saving
# =============================================================================

EMAIL = re.compile(r"[\w.%+-]+@[\w.-]+\.[a-z]{2,}", re.IGNORECASE)
# 7 or more digits in a row, allowing one space, dot, dash or bracket between them:
# catches numbers written with dashes, dots, spaces, brackets, or digit by digit.
DIGIT_RUN = re.compile(r"\+?\(?\d(?:[\s.()-]{0,2}\d){6,}")
# Phone numbers read back in words: "five oh five, five five five, ..." (English and Spanish)
DIGIT_WORD = r"(?:zero|oh|o|one|two|three|four|five|six|seven|eight|nine|cero|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve)"
WORD_RUN = re.compile(rf"\b{DIGIT_WORD}(?:[\s,.-]+{DIGIT_WORD}\b){{6,}}", re.IGNORECASE)

# Structured output fields that hold personal details: never stored.
PERSONAL_FIELD = re.compile(r"name|number|phone|address|email|rider_id", re.IGNORECASE)


def mask_text(text):
    """Replace emails and phone numbers (digits or words) in a piece of text."""
    if text is None:
        return None
    text = EMAIL.sub("<email>", str(text))
    text = WORD_RUN.sub("<number>", text)
    return DIGIT_RUN.sub("<number>", text)


def clean_field_value(field, value):
    """Hide personal fields completely; mask phone numbers/emails in the rest."""
    if PERSONAL_FIELD.search(field):
        return "<redacted>"
    if isinstance(value, (dict, list)):
        value = json.dumps(value)
    return mask_text(value)


# =============================================================================
# 4. Small rules (each one is tested in tests/test_rules.py)
# =============================================================================

# Words in a tool result that mean the tool failed.
ERROR_WORDS = re.compile(
    r"\b(error|failed|failure|exception|timed? ?out|timeout|unavailable|no result returned|internal server)\b",
    re.IGNORECASE,
)


def is_tool_error(result):
    """A tool call failed if no result came back, or the result reports an error.

    Note: a normal answer like "I couldn't find that stop" is NOT an error:
    the tool worked and gave the agent something useful to say.
    """
    if result is None or str(result).strip() == "":
        return True
    return bool(ERROR_WORDS.search(str(result)))


def was_transferred(call):
    """True if the call was handed to a person (any of three signs)."""
    if (call.get("artifact") or {}).get("transfers"):  # Vapi's transfer records
        return True
    reason = call.get("endedReason") or ""  # e.g. "assistant-forwarded-call"
    if "forward" in reason or "transfer" in reason:
        return True
    return any("transfer" in (tool.get("function", {}).get("name") or "").lower()
               for message in messages_of(call) for tool in message.get("toolCalls", []))


def parse_score(text):
    """The first number in the reviewer's score: "8/10" -> 8.0, "Score: 7" -> 7.0."""
    match = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    return float(match.group()) if match else None


NO_ISSUES = {"", "none", "no issues", "none found", "no issues found", "n/a", "na", "nothing", "no", "-"}


def split_issues(text):
    """Split issues_found into separate issues, lower case.

    "Asked two questions at once; long pause" -> ["asked two questions at once", "long pause"]
    """
    if text is None or str(text).strip().lower() in NO_ISSUES:
        return []
    parts = re.split(r"\s*(?:[;\n•]|,\s+|\s-\s)\s*", str(text))
    issues = [part.strip(" -*.").lower() for part in parts]
    return [issue for issue in issues if issue not in NO_ISSUES]


def seconds_between(start, end):
    """Seconds between two ISO date-times like "2026-11-18T21:09:23.577Z"."""
    if not start or not end:
        return None
    parse = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    return (parse(end) - parse(start)).total_seconds()


def messages_of(call):
    """The conversation turns of a call (they live in call.artifact.messages)."""
    return (call.get("artifact") or {}).get("messages") or call.get("messages") or []


def turn_length_seconds(message):
    """How long a turn lasted. Vapi gives times in MILLISECONDS here."""
    if message.get("endTime") and message.get("time"):
        return (message["endTime"] - message["time"]) / 1000
    if message.get("duration") is not None:
        return message["duration"] / 1000
    return None


# =============================================================================
# 5. Saving to the database
# =============================================================================

def open_database(path=DEFAULT_DB):
    """Open (or create) the database and make sure all tables exist."""
    conn = sqlite3.connect(path)
    with open(os.path.join(HERE, "schema.sql")) as f:
        conn.executescript(f.read())
    return conn


def save_calls(conn, calls, agent_names):
    """Save each call and everything in it. Safe to run again: a call that is
    already in the database is deleted and saved fresh (no duplicates)."""
    for call in calls:
        call_id = call["id"]
        artifact = call.get("artifact") or {}

        # Remove this call's old rows first, so re-running never duplicates.
        for table in ("messages", "tool_calls", "costs", "structured_outputs", "quality_reviews", "call_issues"):
            conn.execute(f"DELETE FROM {table} WHERE call_id = ?", (call_id,))

        agent_id = call.get("assistantId")
        if agent_id:
            conn.execute("INSERT OR REPLACE INTO agents (id, name) VALUES (?, ?)",
                         (agent_id, agent_names.get(agent_id, agent_id)))

        # The call itself. (No phone numbers, no recording links.)
        conn.execute(
            "INSERT OR REPLACE INTO calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (call_id, agent_id, call.get("type"), call.get("createdAt"), call.get("startedAt"),
             call.get("endedAt"), seconds_between(call.get("startedAt"), call.get("endedAt")),
             call.get("endedReason"), call.get("cost"), int(was_transferred(call))),
        )

        # Every turn, in order. Tool results are kept so we can match them below.
        results = {}
        for seq, message in enumerate(messages_of(call), start=1):
            role = message.get("role")
            if role == "tool_call_result":
                results[message.get("toolCallId")] = message.get("result")
                text = message.get("result")
            elif role == "tool_calls":
                text = ", ".join(t.get("function", {}).get("name", "?") for t in message.get("toolCalls", []))
            else:
                text = message.get("message")
            conn.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                (call_id, seq, role, message.get("secondsFromStart"), turn_length_seconds(message), mask_text(text)),
            )

        # Every tool call, matched with its result (None = no result came back).
        for message in messages_of(call):
            for tool in message.get("toolCalls", []):
                arguments = tool.get("function", {}).get("arguments")
                if not isinstance(arguments, str):
                    arguments = json.dumps(arguments)
                result = results.get(tool.get("id"))
                conn.execute(
                    "INSERT OR REPLACE INTO tool_calls VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (tool.get("id"), call_id, tool.get("function", {}).get("name"), mask_text(arguments),
                     mask_text(result), message.get("secondsFromStart"), int(is_tool_error(result))),
                )

        # Cost of each part (voice, model, transcriber ...).
        for item in call.get("costs") or []:
            conn.execute("INSERT INTO costs VALUES (?, ?, ?)", (call_id, item.get("type"), item.get("cost")))

        # Structured outputs: one row per field; the quality review also gets its own table.
        for output_id, output in (artifact.get("structuredOutputs") or {}).items():
            name = output.get("name")
            result = output.get("result")
            fields = result if isinstance(result, dict) else {"(value)": result}
            fields = {key.strip(): value for key, value in fields.items()}  # tidy names like "time\t"
            for field, value in fields.items():
                conn.execute("INSERT INTO structured_outputs VALUES (?, ?, ?, ?, ?)",
                             (call_id, output_id, name, field, clean_field_value(field, value)))
            if name == QUALITY_REVIEW:
                save_quality_review(conn, call_id, fields)

    conn.commit()


def save_quality_review(conn, call_id, review):
    """Save one "call quality review" and split its issues_found into rows."""
    text = lambda field: mask_text(review.get(field))
    conn.execute(
        "INSERT OR REPLACE INTO quality_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (call_id, parse_score(review.get("overall_score")), text("overall_score"), text("caller_goal_met"),
         text("caller_sentiment"), text("one_question_per_turn"), text("accuracy"),
         text("remembered_context"), text("issues_found"), text("suggested_prompt_fix")),
    )
    for issue in split_issues(review.get("issues_found")):
        conn.execute("INSERT INTO call_issues VALUES (?, ?)", (call_id, mask_text(issue)))


# =============================================================================
# 6. Run it
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Download recent Vapi calls into calls.db (read-only).")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"how many days back to download (default {DEFAULT_DAYS})")
    parser.add_argument("--db", default=DEFAULT_DB, help="database file (default calls.db)")
    args = parser.parse_args()

    api_key = load_api_key()
    if not api_key:
        raise SystemExit("No VAPI_API_KEY found. Copy .env.example to .env and add your private key.")

    try:
        calls = fetch_recent_calls(api_key, args.days)
        names = find_agent_names(calls, api_key)
    except urllib.error.HTTPError as error:
        # Show Vapi's own explanation (e.g. "your plan only covers the last 14 days").
        raise SystemExit(f"Vapi refused the request (HTTP {error.code}): {error.read().decode()[:300]}")
    conn = open_database(args.db)
    save_calls(conn, calls, names)
    print(f"Saved {len(calls)} calls from the last {args.days} days ({len(names)} agents) to {os.path.basename(args.db)}.")


if __name__ == "__main__":
    main()
