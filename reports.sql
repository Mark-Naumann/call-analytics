-- reports.sql
-- -----------------------------------------------------------------------------
-- Monitoring queries for production voice agents. Run them all with:
--     python3 report.py
-- or one at a time in any SQLite tool:  sqlite3 calls.db
--
-- Each query starts with a "-- name:" line; report.py uses it as the title.
-- "agent" is the Vapi assistant's name (falls back to its ID).
-- -----------------------------------------------------------------------------


-- name: Calls per agent
-- How busy is each agent? A sudden drop can mean a broken phone number or webhook.
SELECT
  COALESCE(a.name, c.agent_id, 'unknown') AS agent,
  COUNT(*)                                AS calls,
  MIN(substr(c.created_at, 1, 10))        AS first_call,   -- just the date part
  MAX(substr(c.created_at, 1, 10))        AS last_call
FROM calls c
LEFT JOIN agents a ON a.id = c.agent_id
GROUP BY agent
ORDER BY calls DESC;


-- name: Average quality score
-- From the "call quality review" structured output (an AI reviewer grades each call).
-- Only calls that have a review are counted.
SELECT
  COALESCE(a.name, c.agent_id, 'unknown') AS agent,
  COUNT(q.call_id)                        AS reviewed_calls,
  ROUND(AVG(q.overall_score), 1)          AS avg_score,
  MIN(q.overall_score)                    AS lowest,
  MAX(q.overall_score)                    AS highest,
  -- How often the reviewer said the caller's goal was met ("yes", "Yes - booked" ...)
  ROUND(100.0 * SUM(CASE WHEN lower(q.caller_goal_met) LIKE 'yes%' THEN 1 ELSE 0 END)
        / COUNT(q.call_id), 1)            AS goal_met_pct
FROM quality_reviews q
JOIN calls c ON c.id = q.call_id
LEFT JOIN agents a ON a.id = c.agent_id
GROUP BY agent
ORDER BY avg_score;                        -- worst first: that's where to look


-- name: Transfer rate
-- Share of calls handed to a person. Rising transfers = the agent can't cope.
SELECT
  COALESCE(a.name, c.agent_id, 'unknown')               AS agent,
  COUNT(*)                                              AS calls,
  SUM(c.was_transferred)                                AS transferred,
  ROUND(100.0 * SUM(c.was_transferred) / COUNT(*), 1)   AS transfer_rate_pct
FROM calls c
LEFT JOIN agents a ON a.id = c.agent_id
GROUP BY agent
ORDER BY transfer_rate_pct DESC;


-- name: Tool error rate
-- Tool calls that failed: no result came back, or the result reported an error
-- (rule: is_tool_error() in fetch_calls.py). Errors here mean callers got no answer.
SELECT
  t.tool_name,
  COUNT(*)                                       AS tool_calls,
  SUM(t.is_error)                                AS errors,
  ROUND(100.0 * SUM(t.is_error) / COUNT(*), 1)   AS error_rate_pct
FROM tool_calls t
GROUP BY t.tool_name
ORDER BY error_rate_pct DESC;


-- name: Dead air (gaps over 3 seconds between turns)
-- Silence between the end of one turn and the start of the next.
-- "agent_slow" = the silence was before the AGENT spoke (slow model or tool);
-- "caller_quiet" = before the CALLER spoke (they may be confused).
WITH turns AS (
  -- Only spoken turns count (not system or tool messages).
  SELECT call_id, role,
         seconds_from_start                                 AS starts_at,
         seconds_from_start + COALESCE(duration_seconds, 0) AS ends_at
  FROM messages
  WHERE role IN ('user', 'bot')
),
gaps AS (
  -- LAG() looks at the previous turn in the same call.
  SELECT call_id, role,
         starts_at - LAG(ends_at) OVER (PARTITION BY call_id ORDER BY starts_at) AS gap_seconds
  FROM turns
)
SELECT
  COALESCE(a.name, c.agent_id, 'unknown')                  AS agent,
  COUNT(DISTINCT c.id)                                     AS calls,
  COUNT(g.gap_seconds)                                     AS gaps_over_3s,
  SUM(CASE WHEN g.role = 'bot'  THEN 1 ELSE 0 END)         AS agent_slow,
  SUM(CASE WHEN g.role = 'user' THEN 1 ELSE 0 END)         AS caller_quiet,
  COUNT(DISTINCT g.call_id)                                AS calls_affected,
  ROUND(MAX(g.gap_seconds), 1)                             AS longest_gap_s
FROM calls c
LEFT JOIN agents a ON a.id = c.agent_id
LEFT JOIN gaps g ON g.call_id = c.id AND g.gap_seconds > 3
GROUP BY agent
ORDER BY gaps_over_3s DESC;


-- name: Average call length and cost
-- Cost per minute is the number to watch when changing voices or models.
SELECT
  COALESCE(a.name, c.agent_id, 'unknown')                    AS agent,
  COUNT(*)                                                   AS calls,
  ROUND(AVG(c.duration_seconds) / 60.0, 1)                   AS avg_minutes,
  ROUND(AVG(c.cost_usd), 3)                                  AS avg_cost_usd,
  ROUND(SUM(c.cost_usd), 2)                                  AS total_cost_usd,
  ROUND(SUM(c.cost_usd) / (SUM(c.duration_seconds) / 60.0), 3) AS cost_per_minute_usd
FROM calls c
LEFT JOIN agents a ON a.id = c.agent_id
GROUP BY agent
ORDER BY total_cost_usd DESC;


-- name: Where the money goes
-- Total cost by part of the system (voice, model, transcriber, Vapi platform ...).
SELECT
  cost_type,
  ROUND(SUM(cost_usd), 3)                                                   AS total_usd,
  ROUND(100.0 * SUM(cost_usd) / (SELECT SUM(cost_usd) FROM costs), 1)       AS share_pct
FROM costs
GROUP BY cost_type
ORDER BY total_usd DESC;


-- name: Most common issues found
-- From issues_found in the quality review, split into one issue per row.
-- The top of this list is the next prompt fix to make.
SELECT
  issue,
  COUNT(*)                AS times_found,
  COUNT(DISTINCT call_id) AS calls
FROM call_issues
GROUP BY issue
ORDER BY times_found DESC, issue
LIMIT 10;
