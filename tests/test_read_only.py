"""Tests that fetch_calls.py only ever READS from Vapi (GET requests only).

Instead of contacting Vapi, these tests swap in a fake "urlopen" that records
every request, so nothing goes over the network.
"""

import io
import json
import os
import re
import unittest
from unittest import mock

import fetch_calls


class FakeResponse(io.BytesIO):
    """Looks enough like a real web response for json.load() and `with`."""


def fake_urlopen(pages, seen):
    """A stand-in for urllib's urlopen: returns the next page, remembers the request."""
    def _urlopen(request, timeout=None):
        seen.append(request)
        return FakeResponse(json.dumps(pages.pop(0)).encode())
    return _urlopen


class TestReadOnly(unittest.TestCase):
    def test_downloading_calls_only_sends_get_requests(self):
        # Page 1 is full (100 calls) so the script asks for page 2 (5 calls), then stops.
        page1 = [{"id": f"c{i}", "createdAt": f"2026-01-05T10:{i % 60:02d}:00Z"} for i in range(100)]
        page2 = [{"id": f"d{i}", "createdAt": "2026-01-04T09:00:00Z"} for i in range(5)]
        seen = []
        with mock.patch("urllib.request.urlopen", fake_urlopen([page1, page2], seen)):
            calls = fetch_calls.fetch_recent_calls("test-key", days=14)

        self.assertEqual(len(calls), 105)
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(r.get_method() == "GET" for r in seen))
        self.assertIn("createdAtLt=", seen[1].full_url)  # page 2 asks for older calls
        self.assertTrue(all(r.full_url.startswith("https://api.vapi.ai/call?") for r in seen))

    def test_looking_up_agent_names_only_sends_get_requests(self):
        calls = [{"id": "c1", "assistantId": "asst-x", "artifact": {"messages": []}}]
        seen = []
        with mock.patch("urllib.request.urlopen", fake_urlopen([{"name": "Agent X"}], seen)):
            names = fetch_calls.find_agent_names(calls, "test-key")
        self.assertEqual(names, {"asst-x": "Agent X"})
        self.assertEqual([r.get_method() for r in seen], ["GET"])

    def test_the_code_has_one_way_to_contact_vapi_and_it_is_get(self):
        path = os.path.join(os.path.dirname(fetch_calls.__file__), "fetch_calls.py")
        with open(path) as f:
            source = f.read()
        self.assertEqual(source.count("urlopen("), 1)                  # only inside vapi_get()
        self.assertEqual(re.findall(r'method="(\w+)"', source), ["GET"])
        # No other web libraries are imported (only urllib, used by vapi_get).
        self.assertIsNone(re.search(r"^\s*(import|from)\s+(requests|httpx|aiohttp|http\.client)\b", source, re.M))


if __name__ == "__main__":
    unittest.main()
