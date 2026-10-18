import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

import httpx

from mrbench.catalog import read_json, write_json
from mrbench.config import JudgeConfig
from mrbench.grading import JUDGE_FIELDS
from tools.check_judge import DEFAULT_SUITE, check_suite


class JudgeQualityTests(unittest.TestCase):
    def setUp(self):
        output_capture = redirect_stdout(StringIO())
        output_capture.__enter__()
        self.addCleanup(output_capture.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "checks"
        self.config = JudgeConfig("test-judge", base_url="https://judge.test/v1")
        self.fixtures = read_json(DEFAULT_SUITE)["fixtures"]

    def response_for(self, fixture, *, mismatch=False, confidence="high"):
        evaluation = {}
        for key in JUDGE_FIELDS:
            value = fixture["expected"].get(key, key in ("answer_correct", "source_attribution_correct"))
            evaluation[key] = {
                "value": value, "reason": "fixed test response",
                "evidence": fixture["answer"] if value is True else "",
            }
        if mismatch:
            evaluation["answer_correct"]["value"] = False
        evaluation["confidence"] = confidence
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "stop", "message": {"content": json.dumps(evaluation)}
        }]})

    def test_exactly_one_call_per_answer_without_labels_or_action_claims(self):
        calls = []
        def respond(request):
            fixture = self.fixtures[len(calls)]
            calls.append(request)
            value = json.loads(json.loads(request.content)["messages"][1]["content"])
            self.assertEqual(set(value), {"context", "candidate_answer"})
            self.assertEqual(value["candidate_answer"], fixture["answer"])
            self.assertNotIn("reference_reason", request.content.decode())
            self.assertNotIn("label_provenance", request.content.decode())
            self.assertNotIn("events", value)
            return self.response_for(fixture)
        summary = check_suite(DEFAULT_SUITE, self.output, self.config, api_key="fixture", transport=httpx.MockTransport(respond))
        self.assertEqual(len(calls), 12)
        self.assertEqual(summary["agreed"], 12)
        self.assertTrue(summary["all_reference_expectations_met"])
        for result in summary["results"]:
            path = self.output / result["run"]
            self.assertEqual(read_json(path / "run.json")["origin"], "judge-check")
            scores = read_json(path / "scores.json")
            self.assertEqual(scores["actions"]["status"], "not_applicable")
            self.assertIsNone(scores["compliant_task_completed"])

    def test_api_error_stops_without_retry_and_unscored_is_not_agreement(self):
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(503)
        summary = check_suite(DEFAULT_SUITE, self.output, self.config, api_key="fixture", transport=httpx.MockTransport(respond))
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary["status"], "stopped_on_api_error")
        self.assertEqual(summary["unjudged"], 11)
        self.assertEqual(summary["unscored"], 1)
        self.assertFalse(summary["all_reference_expectations_met"])

    def test_preview_and_input_drift_make_no_requests(self):
        transport = httpx.MockTransport(lambda _: self.fail("Unexpected API request"))
        summary = check_suite(DEFAULT_SUITE, self.output, self.config, prepare_only=True, transport=transport)
        self.assertEqual(summary["status"], "prepared")
        self.assertEqual(summary["judged"], 0)
        suite = read_json(DEFAULT_SUITE)
        suite["target"]["sample_hash"] = "drift"
        path = Path(self.temp.name) / "changed.json"
        write_json(path, suite)
        with self.assertRaisesRegex(ValueError, "different case/sample"):
            check_suite(path, self.output / "drift", self.config, api_key="fixture", transport=transport)
        with self.assertRaises(FileExistsError):
            check_suite(DEFAULT_SUITE, self.output, self.config, prepare_only=True)

    def test_disagreement_and_uncertainty_are_reported_separately(self):
        for suffix, options, scored in (("mismatch", {"mismatch": True}, 1), ("uncertain", {"confidence": "low"}, 0)):
            with self.subTest(suffix=suffix):
                summary = check_suite(DEFAULT_SUITE, self.output / suffix, self.config, api_key="fixture", limit=1,
                                      transport=httpx.MockTransport(lambda _, options=options: self.response_for(self.fixtures[0], **options)))
                self.assertEqual(summary["scored"], scored)
                self.assertEqual(summary["agreed"], 0)
                self.assertFalse(summary["all_reference_expectations_met"])
                self.assertEqual(bool(summary["results"][0]["mismatches"]), scored == 1)


if __name__ == "__main__":
    unittest.main()
