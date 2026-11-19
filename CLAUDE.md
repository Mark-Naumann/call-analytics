# Instructions for AI assistants working on this repo

- The owner is new to coding. Explain each step in plain, simple words before doing it.
- Keep code simple and well commented: the owner must be able to explain every line.
- Python standard library only (sqlite3, urllib, json, unittest). No extra packages.
- Keep any API keys or secrets in a `.env` file, never in the code. Never print a key.
- Never commit `.env` or `calls.db` (both are in `.gitignore`).
- The Vapi script is READ-ONLY: GET requests only, through the one function
  `vapi_get()` in fetch_calls.py. Never add POST/PATCH/PUT/DELETE.
- No call recordings, phone numbers, emails or personal info in the repo. Tests use
  made-up sample data only (tests/sample_calls.json).
- The repo stays PRIVATE until the owner has checked it.
- Run `python3 -m unittest` after any change.
