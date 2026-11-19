# call-analytics — How I'd monitor production voice agents

**A small, read-only pipeline that pulls every call my Vapi voice agents handled into a
SQLite database and answers the questions an operator asks every morning: are the agents
busy, are they good, are they breaking, and what do they cost?**

Built for my two demo agents, Sam v14 (Naumann Painting receptionist) and Jordan v10
(Juniper Valley Transit customer service), but nothing in it is specific to them.

🎬 **Demo video:** coming soon

---

## Why these metrics

A voice agent can "work" in a test call and still fail real callers. These are the
signals I'd watch in production, and what I'd do when one moves:

| Metric | What it tells me | If it gets worse, I… |
|---|---|---|
| **Calls per agent** | Traffic, and whether calls are arriving at all | Check the phone number, webhook and Vapi status |
| **Average quality score** | An AI reviewer's grade for each call ("call quality review" structured output) | Read the lowest-scoring calls first |
| **Transfer rate** | How often the agent hands off to a person | Find which request types it can't handle |
| **Tool error rate** | Tool calls that failed or returned an error (no result, timeouts, "Error: …") | Check the tool's API (here: transit-sim); callers got no answer |
| **Dead air** (gaps > 3 s) | Awkward silences, split by who was quiet: **agent_slow** (model/tool latency) vs **caller_quiet** (caller confused or thinking) | agent_slow → faster model, shorter prompt, filler message while tools run; caller_quiet → clearer questions |
| **Call length and cost** | Average minutes, cost per call, **cost per minute** | Compare voices and models before switching |
| **Where the money goes** | Cost split: Vapi platform, voice, model, transcriber | Spend tuning effort where the money is |
| **Most common issues** | The reviewer's `issues_found`, counted | The top issue is the next prompt fix |

### First findings (my test calls, Nov 17–18, Mountain Time)

- 27 calls: 19 for Sam, 8 for Jordan; about 1 minute each, **$0.08–0.09 per minute**.
- **Over half the cost (55%) is the Vapi platform fee**, then voice (24%). The LLM is
  about 10%, so a cheaper model would barely change the bill.
- Dead air is mostly **caller_quiet** (23 of 26 long gaps), the caller thinking or
  unsure what to say, rather than the agent being slow. That points to clearer
  questions, which is what the "one question per turn" prompt change targets.
- Tools: `get_next_bus` 4 calls, `plan_trip` 1, `transfer_to_person` 1, **0 errors**.
  Jordan's transfer rate is 12.5% (1 of 8 calls, a real transfer to a person). A
  successful transfer returns "Transfer initiated." and is (correctly) not a tool error.
- Quality reviews: the first 3 reviewed calls scored 8, 8 (Jordan) and 7 (Sam). The top
  issue is **phone-number read-back**, which led to the Jordan v10 fix described in
  [call-analyzer](https://github.com/Mark-Naumann/call-analyzer).

## How it works

```
Vapi API  ──(GET only)──►  fetch_calls.py  ──►  calls.db (SQLite)  ──►  report.py  ──►  text report
                              │                       ▲                     │
                              │ removes personal      │ schema.sql          │ runs reports.sql
                              │ info before saving    │ (tables)            │ (commented queries)
```

1. **`fetch_calls.py`** downloads the last 14 days of calls (my Vapi plan's history
   limit), 100 at a time, and saves them into clear tables. Running it again updates
   calls instead of duplicating them.
2. **`schema.sql`** defines the tables: `agents`, `calls`, `messages` (each turn, with
   timing), `tool_calls` (matched with their results), `costs`, `structured_outputs`
   (every field, one row each), `quality_reviews` and `call_issues`.
3. **`reports.sql`** holds one commented query per metric. The dead-air query uses a
   window function (`LAG()`) to compare each turn with the one before it.
4. **`report.py`** runs every query and prints a simple text table for each.

### Read-only by design

The script has **exactly one** function that talks to Vapi, `vapi_get()`, and it can
only send GET requests. A test reads the source code to check that this is still true
(one `urlopen`, only `method="GET"`, no other web libraries), and another test records
every request made while downloading and checks that all of them are GETs.

### Privacy by design

The database only ever lives on my computer (`calls.db` is in `.gitignore`), and even
there it holds as little personal data as possible:

- **Never stored:** caller phone numbers and call recording links.
- **Hidden:** structured-output fields with personal details (names, callback numbers,
  addresses, rider IDs) are saved as `<redacted>`.
- **Masked in text:** phone numbers (digits, or read back in words like "five oh
  five…", English and Spanish) and emails become `<number>` and `<email>`.
- The tests use **made-up** calls only (`tests/sample_calls.json`), and check that no
  personal data ends up in any table.

## Run it

Needs Python 3.10+. Standard library only, so there's nothing to install.

```bash
cp .env.example .env        # then paste your Vapi PRIVATE API key into .env
python3 fetch_calls.py      # download the last 14 days into calls.db
python3 report.py           # print the report
```

Explore the data yourself:

```bash
sqlite3 calls.db "SELECT ended_reason, COUNT(*) FROM calls GROUP BY ended_reason;"
```

## Tests

```bash
python3 -m unittest
```

40 tests, no network needed:

| File | Checks |
|---|---|
| `tests/test_rules.py` | Phone/email masking (all formats), personal-field hiding, what counts as a tool error (a successful transfer is not one), transfer detection, score parsing, issue splitting, timing units |
| `tests/test_database.py` | Every table is filled correctly from the sample calls; re-running doesn't duplicate; **no personal info anywhere in the database** |
| `tests/test_reports.py` | Every query in `reports.sql` returns the numbers worked out by hand; the printed report has every section |
| `tests/test_read_only.py` | Every request to Vapi is a GET; paging works; the code has only one way to contact Vapi |

## Things I learned from the real data

- Vapi's message `duration`, `time` and `endTime` are in **milliseconds**, even though the
  docs say seconds. Dead-air numbers would be off by 1000× without checking.
- Vapi's firewall rejects Python's default user agent ("error code 1010"), so requests
  send their own (`call-analytics/1.0`).
- The plan's history limit (14 days) comes back as an HTTP 400 with a clear message;
  the script shows that message instead of a stack trace.
- Real structured-output data can have untidy field names (one had a trailing tab), so
  field names are cleaned on the way in.

## What I'd do next

- **Fix issue counting:** the reviewer writes `issues_found` as long sentences, and
  splitting them on commas breaks them into fragments, so "Most common issues" doesn't
  group well yet. Better: have the reviewer pick from fixed labels (`phone_readback`,
  `asked_two_questions`, …), which also keeps callers' names out of the issue text.
- **Run it on a schedule** (e.g. every hour) and **alert** when a metric crosses a line:
  tool error rate > 5%, average score < 7, agent_slow gaps on > 10% of calls, or calls
  per hour dropping to zero during business hours.
- **Compare prompt versions:** calls record the assistant version, so scores and dead
  air could be compared before and after each prompt change (like an A/B test).
- **Latency:** Vapi's `performanceMetrics` (model and voice response times) would show
  exactly where agent_slow time goes.
- **A dashboard** on top of the same SQL (the queries don't change).
- **Ask for a consistent score scale** (e.g. always 1–10) in the quality review prompt,
  so averages are comparable.

## Related projects

| Repo | What it is |
|---|---|
| [call-analyzer](https://github.com/Mark-Naumann/call-analyzer) | The "call quality review" these quality scores come from, with real findings |
| [painting-agent](https://github.com/Mark-Naumann/painting-agent) | Sam, AI receptionist for a painting company (Vapi) |
| [transit-agent](https://github.com/Mark-Naumann/transit-agent) | Jordan, AI customer service for a fictional transit agency (Vapi) |
| [transit-sim](https://github.com/Mark-Naumann/transit-sim) | The simulated bus system and API Jordan's tools call |
