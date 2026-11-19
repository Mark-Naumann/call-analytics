"""Tests for the small rules in fetch_calls.py (privacy, errors, transfers, scores)."""

import unittest

import fetch_calls as fc

# Fictional numbers (555-01xx is reserved for fiction), built here at run time so
# no phone-number-shaped text is stored in the repo.
FAKE_DIGITS = "505" + "555" + "0199"
FAKE_DASHED = "-".join([FAKE_DIGITS[:3], FAKE_DIGITS[3:6], FAKE_DIGITS[6:]])
FAKE_SPACED = " ".join(FAKE_DIGITS)
FAKE_WORDS = "five oh five, five five five, oh one nine nine"
FAKE_EMAIL = "someone" + "@" + "example.com"


class TestPrivacy(unittest.TestCase):
    def test_phone_numbers_are_masked_in_any_format(self):
        for number in [FAKE_DIGITS, FAKE_DASHED, f"({FAKE_DIGITS[:3]}) {FAKE_DIGITS[3:6]} {FAKE_DIGITS[6:]}",
                       "+1 " + FAKE_DASHED, FAKE_SPACED]:
            self.assertEqual(fc.mask_text(f"call me at {number} please"), "call me at <number> please", number)

    def test_phone_numbers_read_back_in_words_are_masked(self):
        self.assertEqual(fc.mask_text(f"That's {FAKE_WORDS}, right?"), "That's <number>, right?")
        self.assertIn("<number>", fc.mask_text("cinco cero cinco cinco cinco cinco cero uno nueve nueve"))

    def test_emails_are_masked(self):
        self.assertEqual(fc.mask_text(f"email {FAKE_EMAIL} thanks"), "email <email> thanks")

    def test_normal_text_is_left_alone(self):
        text = "The next Route 2 bus reaches Main Library at 10:33 AM, in 6 minutes. Fare $1.50."
        self.assertEqual(fc.mask_text(text), text)

    def test_personal_fields_are_hidden(self):
        for field in ["rider_name", "caller_name", "callback_number", "pickup_address", "paratransit_rider_id"]:
            self.assertEqual(fc.clean_field_value(field, "anything"), "<redacted>", field)
        self.assertEqual(fc.clean_field_value("request_type", "info"), "info")
        self.assertEqual(fc.clean_field_value("is_urgent", True), "True")


class TestToolErrors(unittest.TestCase):
    def test_no_result_is_an_error(self):
        self.assertTrue(fc.is_tool_error(None))
        self.assertTrue(fc.is_tool_error("  "))

    def test_error_words_are_errors(self):
        for result in ["Error: request timed out", "Request failed with status 500", "No result returned.",
                       "Service unavailable", "timeout"]:
            self.assertTrue(fc.is_tool_error(result), result)

    def test_helpful_answers_are_not_errors(self):
        for result in ["The next Route 2 bus reaches Main Library in 6 minutes.",
                       "I couldn't find that stop on Route 3. Its stops are: ..."]:
            self.assertFalse(fc.is_tool_error(result), result)


class TestTransfers(unittest.TestCase):
    def test_three_signs_of_a_transfer(self):
        self.assertTrue(fc.was_transferred({"artifact": {"transfers": [{"status": "completed"}]}}))
        self.assertTrue(fc.was_transferred({"endedReason": "assistant-forwarded-call"}))
        tool_message = {"role": "tool_calls", "toolCalls": [{"function": {"name": "transferCall"}}]}
        self.assertTrue(fc.was_transferred({"artifact": {"messages": [tool_message]}}))

    def test_normal_call_is_not_a_transfer(self):
        self.assertFalse(fc.was_transferred({"endedReason": "customer-ended-call", "artifact": {"messages": []}}))


class TestScoresAndIssues(unittest.TestCase):
    def test_score_is_the_first_number(self):
        self.assertEqual(fc.parse_score("8/10"), 8.0)
        self.assertEqual(fc.parse_score("Score: 7.5"), 7.5)
        self.assertEqual(fc.parse_score("9"), 9.0)
        self.assertIsNone(fc.parse_score("n/a"))
        self.assertIsNone(fc.parse_score(None))

    def test_issues_are_split_and_lower_cased(self):
        self.assertEqual(fc.split_issues("Asked two questions; Long pause."), ["asked two questions", "long pause"])
        self.assertEqual(fc.split_issues("- repeated itself\n- skipped recap"), ["repeated itself", "skipped recap"])
        self.assertEqual(fc.split_issues("misheard name, tool error"), ["misheard name", "tool error"])

    def test_no_issues(self):
        for text in [None, "", "None", "No issues found", "n/a"]:
            self.assertEqual(fc.split_issues(text), [], text)


class TestTiming(unittest.TestCase):
    def test_turn_length_uses_milliseconds(self):
        # Vapi gives time/endTime/duration in milliseconds.
        self.assertEqual(fc.turn_length_seconds({"time": 1000, "endTime": 3500, "duration": 2000}), 2.5)
        self.assertEqual(fc.turn_length_seconds({"duration": 1500}), 1.5)
        self.assertIsNone(fc.turn_length_seconds({}))

    def test_call_length(self):
        self.assertEqual(fc.seconds_between("2026-01-05T10:00:00.000Z", "2026-01-05T10:02:30.500Z"), 150.5)
        self.assertIsNone(fc.seconds_between(None, "2026-01-05T10:00:00Z"))


if __name__ == "__main__":
    unittest.main()
