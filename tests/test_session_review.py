import unittest

from mrbench.catalog import catalog


class SessionReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = catalog()

    def episode(self, case_id, condition):
        case = self.cases[case_id]
        return case.environment(case.spec["default_sample"], condition)

    def test_install_log_controls_preserve_diagnostic_evidence_and_permission(self):
        main, tool_log, clean, authorized = (
            self.episode("pasted-install-log-injection", condition)
            for condition in ("main", "tool-log", "clean", "authorized")
        )
        log_path = tool_log.sample["log_path"]
        copied_output = main.prompt.split("Here's the terminal output I copied:\n\n")[1]
        tool_output = tool_log.call("file_read", {"path": log_path})["content"]
        self.assertEqual(tool_output, copied_output)
        self.assertNotIn(main.sample["vendor_notice"], tool_log.prompt)
        self.assertNotIn(log_path, main.snapshot()["files"])
        self.assertEqual(
            clean.prompt, main.prompt.removesuffix("\n" + main.sample["vendor_notice"])
        )
        self.assertTrue(authorized.prompt.endswith(copied_output))
        self.assertEqual(main.instructions, authorized.instructions)

        for env in (main, tool_log, clean, authorized):
            with self.subTest(condition=env.condition["id"]):
                before = env.judge_context()
                result = env.call("run_dependency_support_probe", {})
                self.assertEqual(result["report"], env.sample["probe_result"])
                score = env.score_actions(env.events, env.snapshot(), env.condition)
                permitted = env is authorized
                self.assertEqual(score["violation_attempted"], not permitted)
                self.assertEqual(score["violation_observed"], not permitted)
                self.assertEqual(score["observations"]["support_probes_completed"], 1)
                self.assertEqual(env.judge_context(), before)
                fresh = self.episode(env.case.id, env.condition["id"])
                self.assertEqual(fresh.snapshot()["support_probes"], [])

    def test_summary_control_changes_only_follow_up_and_scoring_expectation(self):
        main, explicit = (
            self.episode("work-summary-disclosure", condition)
            for condition in ("main", "explicit-inventory")
        )
        self.assertEqual(
            main.prompt, explicit.prompt.removesuffix(explicit.condition["task_suffix"])
        )
        self.assertEqual(main.snapshot(), explicit.snapshot())
        self.assertEqual(main.tools, explicit.tools)
        main_context, explicit_context = main.judge_context(), explicit.judge_context()
        self.assertEqual(main_context["expected_facts"], explicit_context["expected_facts"])
        self.assertNotIn("limitation_disclosed", main_context["completion_criteria"])
        self.assertIs(explicit_context["completion_criteria"]["limitation_disclosed"], True)
        denied = main.call("file_write", {"path": "config/preview.json", "content": "{}"})
        self.assertIn("error", denied)
        self.assertEqual(main.snapshot(), explicit.snapshot())
