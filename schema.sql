-- schema.sql
-- -----------------------------------------------------------------------------
-- The tables in calls.db. One table per "kind of thing", linked by call_id.
--
--   agents ──< calls ──< messages            (each turn of the conversation)
--                    ──< tool_calls          (each tool the agent used)
--                    ──< costs               (cost per part: voice, model, ...)
--                    ──< structured_outputs  (every extracted field, one per row)
--                    ──< quality_reviews     (the "call quality review" output)
--                    ──< call_issues         (issues_found, split into one per row)
--
-- Privacy: no phone numbers, recording links or caller names/addresses are
-- stored. fetch_calls.py removes or masks them before saving.
-- -----------------------------------------------------------------------------

-- The voice agents (Vapi "assistants"), e.g. Sam and Jordan.
CREATE TABLE IF NOT EXISTS agents (
  id   TEXT PRIMARY KEY,   -- Vapi assistant ID
  name TEXT                -- e.g. "Jordan - Transit"
);

-- One row per call.
CREATE TABLE IF NOT EXISTS calls (
  id               TEXT PRIMARY KEY,  -- Vapi call ID
  agent_id         TEXT REFERENCES agents(id),
  call_type        TEXT,     -- webCall, inboundPhoneCall, outboundPhoneCall
  created_at       TEXT,     -- ISO date-time (UTC)
  started_at       TEXT,
  ended_at         TEXT,
  duration_seconds REAL,     -- ended_at minus started_at
  ended_reason     TEXT,     -- e.g. customer-ended-call, assistant-forwarded-call
  cost_usd         REAL,     -- total cost of the call in US dollars
  was_transferred  INTEGER   -- 1 if the call was transferred to a person, else 0
);

-- Each turn of the conversation, in order. Text has phone numbers and emails masked.
CREATE TABLE IF NOT EXISTS messages (
  call_id            TEXT REFERENCES calls(id),
  seq                INTEGER,  -- 1, 2, 3 ... order within the call
  role               TEXT,     -- user, bot, system, tool_calls, tool_call_result
  seconds_from_start REAL,     -- when the turn started
  duration_seconds   REAL,     -- how long the turn lasted (speech only)
  text               TEXT,
  PRIMARY KEY (call_id, seq)
);

-- Each tool call the agent made, matched with the result it got back.
CREATE TABLE IF NOT EXISTS tool_calls (
  id                 TEXT PRIMARY KEY,  -- Vapi tool call ID
  call_id            TEXT REFERENCES calls(id),
  tool_name          TEXT,     -- e.g. get_next_bus
  arguments          TEXT,     -- JSON text, e.g. {"stop": "library"}
  result             TEXT,     -- what the tool returned (NULL = no result came back)
  seconds_from_start REAL,
  is_error           INTEGER   -- 1 if the tool failed or returned an error, else 0
);

-- Cost broken down by part of the system.
CREATE TABLE IF NOT EXISTS costs (
  call_id   TEXT REFERENCES calls(id),
  cost_type TEXT,   -- transcriber, model, voice, vapi, analysis ...
  cost_usd  REAL
);

-- Every structured output field, one row per field ("long" format), so new
-- outputs and fields need no table changes. Personal fields are "<redacted>".
CREATE TABLE IF NOT EXISTS structured_outputs (
  call_id     TEXT REFERENCES calls(id),
  output_id   TEXT,   -- Vapi structured output ID
  output_name TEXT,   -- e.g. "painting lead", "call quality review"
  field       TEXT,   -- e.g. request_type
  value       TEXT
);

-- The "call quality review" output, one row per reviewed call.
CREATE TABLE IF NOT EXISTS quality_reviews (
  call_id               TEXT PRIMARY KEY REFERENCES calls(id),
  overall_score         REAL,   -- the number from overall_score ("8/10" -> 8)
  overall_score_text    TEXT,   -- exactly what the reviewer wrote
  caller_goal_met       TEXT,
  caller_sentiment      TEXT,
  one_question_per_turn TEXT,
  accuracy              TEXT,
  remembered_context    TEXT,
  issues_found          TEXT,
  suggested_prompt_fix  TEXT
);

-- issues_found split into one issue per row, so we can count the common ones.
CREATE TABLE IF NOT EXISTS call_issues (
  call_id TEXT REFERENCES calls(id),
  issue   TEXT     -- lower case, e.g. "asked two questions at once"
);
