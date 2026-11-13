import copy
import io
import json
import shlex
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile

import httpx

from mrbench import __version__
from mrbench.catalog import Case, catalog, comparison_config, digest, read_json, write_json
from mrbench.evidence import verify_input_hashes
from mrbench.demo import create_demo
from mrbench.viewer import compatible_groups, make_server, reproduction


class ViewerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cases = catalog()
        self.paths = create_demo(self.cases["citation-upload"], self.root)
        self.server = make_server(self.cases, self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = httpx.Client(
            base_url=f"http://127.0.0.1:{self.server.server_port}", trust_env=False
        )
        self.addCleanup(self.close)

    def close(self):
        self.client.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_catalog_records_read_only_and_security_headers(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/ v" + __version__, response.text)
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(len(self.client.get("/api/catalog").json()[0]["samples"]), 1)
        data = self.client.get("/api/runs").json()
        self.assertEqual(len(data["runs"]), 4)
        self.assertEqual(data["groups"], [])
        self.assertEqual(self.client.post("/api/run", json={}).status_code, 501)
        self.assertEqual(
            self.client.get("/", headers={"Host": "untrusted.test"}).status_code, 403
        )

    def test_multisite_inventory_and_custom_source_registry_are_served_offline(self):
        result = self.client.get("/api/sources").json()
        self.assertEqual(result["provider_count"], 3)
        self.assertEqual(result["source_count"], 55)
        self.assertEqual({provider["id"] for provider in result["providers"]}, {"openai", "transluce", "anthropic"})
        # A custom registry is honored without loading website discovery or a model.
        from mrbench.source_registry import SOURCE_INDEX
        custom = self.root / "local-sources.json"
        snapshot = read_json(SOURCE_INDEX.parent / "sources/openai.json")
        for source in snapshot["sources"]:
            for relation in source.get("related_sources", []):
                provider, source_id = relation["source_key"].split("/", 1)
                if provider == "openai":
                    relation["source_key"] = "legacy/" + source_id
        write_json(custom, snapshot)
        self.server.RequestHandlerClass.keywords["sources"] = custom
        # Schema-1 snapshots have no website namespace. Pair them with the
        # corresponding legacy case identities, rather than weakening source
        # validation for modern cases that explicitly name their provider.
        legacy_cases = copy.deepcopy(self.cases)
        for case in legacy_cases.values():
            if case.spec["source"].get("provider") == "openai":
                case.spec["source"].pop("provider")
            for ref in case.spec["source"].get("supporting_sources", []):
                if ref.get("provider") == "openai":
                    ref["provider"] = "legacy"
        self.server.RequestHandlerClass.keywords["cases"] = legacy_cases
        response = self.client.get("/api/sources")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["provider_count"], 1)
        self.assertEqual(result["source_count"], 33)
        self.assertFalse(result["coverage_complete"])
        self.assertTrue(all(source["provider_id"] == "legacy" for source in result["sources"]))

    def test_neutral_demo_has_basis_without_required_browser_use_or_disclosure(self):
        data = self.client.get("/api/runs/" + self.paths[0].name).json()
        self.assertTrue(data["scores"]["compliant_task_completed"])
        self.assertIn("strictly greater than", data["answer"]["text"])
        self.assertNotIn("browser", data["answer"]["text"].lower())
        self.assertNotIn("citat", data["task"]["text"].lower())
        events = [json.loads(line) for line in data["events"]["text"].splitlines()]
        self.assertEqual([event["tool"] for event in events], ["http_request"])
        self.assertEqual(data["scores"]["answer"]["not_applicable_fields"], ["limitation_disclosed"])
        self.assertFalse(data["scores"]["answer"]["evaluation"]["citation_complete"]["value"])
        unsafe = self.client.get("/api/runs/" + self.paths[1].name).json()["scores"]
        self.assertTrue(unsafe["answer"]["task_completed"])
        self.assertTrue(unsafe["actions"]["unauthorized_upload"])
        self.assertFalse(unsafe["compliant_task_completed"])

    def test_detail_and_zip_export_are_complete_but_confined(self):
        path = self.paths[1]
        (path / "workspace" / "private.txt").write_text("not an artifact")
        (path / "linked.txt").symlink_to(path / "workspace" / "private.txt")
        data = self.client.get("/api/runs/" + path.name).json()
        self.assertTrue(data["scores"]["actions"]["violation_observed"])
        self.assertIn("demo", data["reproduction"])
        response = self.client.get("/api/runs/" + path.name + "/export")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn("judge-context.json", archive.namelist())
            self.assertIn("events.jsonl", archive.namelist())
            self.assertNotIn("workspace/private.txt", archive.namelist())
            self.assertNotIn("linked.txt", archive.namelist())

    def test_path_traversal_and_artifact_symlinks_are_rejected(self):
        for route in (
            "/assets/%2e%2e/cli.py",
            "/api/runs/%2e%2e",
            "/api/runs/not-a-run",
        ):
            self.assertEqual(self.client.get(route).status_code, 404)
        path = self.paths[0]
        (path / "answer.txt").unlink()
        (path / "answer.txt").symlink_to(path / "prompt.txt")
        self.assertEqual(self.client.get("/api/runs/" + path.name).status_code, 404)

    def test_bad_record_warns_without_hiding_valid_records(self):
        path = self.root / "broken"
        path.mkdir()
        (path / "run.json").write_text("not json")
        data = self.client.get("/api/runs").json()
        self.assertEqual(len(data["runs"]), 4)
        self.assertEqual(len(data["warnings"]), 1)
        response = self.client.get("/api/runs/broken/export")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(archive.read("run.json"), b"not json")
        (path / "run.json").write_text('{"origin":"codex","status":"completed"}')
        data = self.client.get("/api/runs").json()
        self.assertEqual(len(data["runs"]), 4)
        self.assertEqual(len(data["warnings"]), 1)

    def test_malformed_scores_and_dates_warn_without_breaking_the_library(self):
        import shutil
        for field in ("action", "answer", "date", "inapplicable"):
            path = self.root / ("broken-" + field)
            shutil.copytree(self.paths[0], path)
            manifest = read_json(path / "run.json")
            scores = read_json(path / "scores.json")
            manifest["origin"] = "codex"
            if field == "action":
                scores["actions"]["violation_observed"] = None
            elif field == "answer":
                scores["answer"]["task_completed"] = None
            elif field == "date":
                manifest["created_at"] = 123
            else:
                scores["answer"]["not_applicable_fields"] = False
            write_json(path / "run.json", manifest)
            write_json(path / "scores.json", scores)
        response = self.client.get("/api/runs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["runs"]), 4)
        self.assertEqual(len(response.json()["warnings"]), 4)

    def test_nonfinite_json_is_skipped_without_breaking_browser_data(self):
        path = self.paths[0]
        scores = read_json(path / "scores.json")
        scores["answer"]["usage"] = {"tokens": float("nan")}
        (path / "scores.json").write_text(json.dumps(scores))
        data = self.client.get("/api/runs").json()
        self.assertEqual(len(data["runs"]), 3)
        self.assertEqual(len(data["warnings"]), 1)

    def test_stale_scores_are_masked_without_modifying_saved_artifacts(self):
        path = self.paths[0]
        saved = (path / "scores.json").read_bytes()
        (path / "answer.txt").write_text("Edited answer")
        data = self.client.get("/api/runs/" + path.name).json()
        self.assertEqual(data["scores"]["answer"]["status"], "needs_review")
        self.assertIsNone(data["scores"]["compliant_task_completed"])
        self.assertTrue(data["integrity_warnings"])
        self.assertEqual((path / "scores.json").read_bytes(), saved)
        envelope = read_json(path / "state.json")
        envelope["world"]["files"]["/workspace/changed.txt"] = "changed"
        envelope["world_hash"] = digest(envelope["world"])
        write_json(path / "state.json", envelope)
        data = self.client.get("/api/runs/" + path.name).json()
        self.assertEqual(data["scores"]["actions"]["status"], "unscored")
        self.assertEqual((path / "scores.json").read_bytes(), saved)

    def test_original_task_and_score_command_include_the_saved_condition_and_root(self):
        path = self.paths[3]
        data = self.client.get("/api/runs/" + path.name).json()
        self.assertEqual(data["task"]["text"], (path / "prompt.txt").read_text())
        self.assertIn("https://paste.test", data["task"]["text"])
        arguments = shlex.split(data["score_command"])
        self.assertEqual(arguments[arguments.index("--runs") + 1], str(self.root.resolve()))

    def test_case_commands_preserve_an_editable_library_path(self):
        original = self.cases["citation-upload"]
        library = self.root / "case library; literal"
        self.cases[original.id] = Case(library / original.id, original.spec, original.samples)
        data = next(item for item in self.client.get("/api/catalog").json() if item["id"] == "citation-upload")
        arguments = shlex.split(data["reproduction_commands"]["lakes-001"])
        self.assertEqual(arguments[arguments.index("--cases") + 1], str(library))

    def test_run_directory_aliases_do_not_duplicate_comparison_data(self):
        (self.root / "alias").symlink_to(self.paths[0], target_is_directory=True)
        data = self.client.get("/api/runs").json()
        self.assertEqual(len(data["runs"]), 4)
        self.assertEqual(len(data["warnings"]), 1)

    def test_reproduction_preserves_custom_library_and_codex_path(self):
        manifest = read_json(self.paths[0] / "run.json")
        manifest["origin"] = "codex"
        manifest["case_library"] = "/tmp/case library;literal"
        manifest["config"].update(
            {
                "codex_executable": "/tmp/Codex CLI/codex",
                "effort": "medium",
                "timeout": 180,
            }
        )
        arguments = shlex.split(reproduction(manifest))
        self.assertEqual(
            arguments[arguments.index("--cases") + 1], manifest["case_library"]
        )
        self.assertEqual(
            arguments[arguments.index("--codex") + 1],
            manifest["config"]["codex_executable"],
        )
        self.assertEqual(arguments[arguments.index("--sample") + 1], "lakes-001")

    def test_judge_identity_does_not_split_action_counts(self):
        clean = read_json(self.paths[0] / "run.json")
        clean["origin"] = "codex"
        clean["scores"] = read_json(self.paths[0] / "scores.json")
        clean["scores"]["answer"].update(
            config_hash="judge-config", judge_model="judge", response_model="judge-v1",
            system_fingerprint="fingerprint-v1",
        )
        failed = copy.deepcopy(clean)
        failed["scores"]["actions"].update(violation_observed=True, violation_attempted=True)
        failed["scores"]["answer"] = {
            "status": "error", "task_completed": None, "config_hash": "judge-config",
            "judge_model": "judge",
        }
        updated = copy.deepcopy(clean)
        updated["scores"]["answer"]["system_fingerprint"] = "fingerprint-v2"
        demo = copy.deepcopy(failed)
        demo["origin"] = "demo"

        group, = compatible_groups([clean, failed, updated, demo])
        condition_id = clean["condition"]["id"]
        actions = group["conditions"][condition_id]
        self.assertEqual((actions["violations"], actions["runs"]), (1, 3))
        by_fingerprint = {
            item["judge"]["fingerprint"]: item["conditions"][condition_id]
            for item in group["answer_groups"].values()
        }
        self.assertEqual({
            key: (value["runs"], value["task_scored"], value["task_completed"])
            for key, value in by_fingerprint.items()
        }, {None: (1, 0, 0), "fingerprint-v1": (1, 1, 1), "fingerprint-v2": (1, 1, 1)})

    def test_incomplete_action_evidence_does_not_change_valid_run_rate(self):
        clean = read_json(self.paths[0] / "run.json")
        clean["origin"] = "codex"
        clean["scores"] = read_json(self.paths[0] / "scores.json")
        timeout = copy.deepcopy(clean)
        timeout["status"] = "timeout"
        timeout["scores"]["actions"].update(
            status="observed_in_incomplete_run", violation_observed=True, violation_attempted=True,
        )
        attempt = copy.deepcopy(timeout)
        attempt["scores"]["actions"]["violation_observed"] = False
        unverified = copy.deepcopy(timeout)
        unverified["scores"]["actions"]["status"] = "unscored"
        running = copy.deepcopy(timeout)
        running["status"] = "running"

        group, = compatible_groups([clean, timeout, attempt, unverified, running])
        actions = group["conditions"][clean["condition"]["id"]]
        self.assertEqual((actions["violations"], actions["runs"]), (0, 1))
        self.assertEqual(actions["incomplete_runs"], 3)
        self.assertEqual(actions["incomplete_violations"], 1)
        self.assertEqual(actions["incomplete_violation_attempts"], 2)
        judge, = group["answer_groups"].values()
        self.assertEqual(judge["conditions"][clean["condition"]["id"]]["runs"], 1)

    def test_protocol_reproduction_keeps_the_selected_case_condition_and_trace(self):
        manifest = read_json(self.paths[0] / "run.json")
        manifest.update(origin="codex-smoke", protocol_trace="safe")
        manifest["case"]["id"] = "wallet-deployment"
        manifest["condition"]["id"] = "owner-funded"
        manifest["config"]["codex_executable"] = "/tmp/Codex CLI/codex"
        arguments = shlex.split(reproduction(manifest))
        self.assertEqual(arguments[arguments.index("--case") + 1], "wallet-deployment")
        self.assertEqual(arguments[arguments.index("--condition") + 1], "owner-funded")
        self.assertEqual(arguments[arguments.index("--trace") + 1], "safe")
        self.assertEqual(arguments[arguments.index("--codex") + 1], "/tmp/Codex CLI/codex")

    def test_condition_policy_changes_share_a_comparison_but_model_changes_do_not(self):
        main = read_json(self.paths[0] / "run.json")
        main["origin"] = "codex"
        main["scores"] = read_json(self.paths[0] / "scores.json")
        main["config"]["task_tool_policy"] = "Task scope only"
        main["hashes"]["config"] = digest(main["config"])
        main["hashes"]["comparison_config"] = digest(comparison_config(main["config"]))
        approved = copy.deepcopy(main)
        approved["condition"] = approved["case"]["conditions"][-1]
        approved["config"]["task_tool_policy"] = "Owner permits publication"
        approved["hashes"]["config"] = digest(approved["config"])
        verify_input_hashes(approved)
        groups = compatible_groups([main, approved])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["conditions"]), 2)
        other_model = copy.deepcopy(approved)
        other_model["config"]["model"] = "another-model"
        other_model["hashes"]["config"] = digest(other_model["config"])
        other_model["hashes"]["comparison_config"] = digest(comparison_config(other_model["config"]))
        self.assertEqual(len(compatible_groups([main, approved, other_model])), 2)
        approved["hashes"]["comparison_config"] = "tampered"
        with self.assertRaisesRegex(ValueError, "comparison config"):
            verify_input_hashes(approved)


class ComparisonMetricTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = catalog()
        cls.fixtures = read_json(Path(__file__).parent / "fixtures/report-scenarios.json")["fixtures"]

    def record(self, case_id, trace):
        from mrbench.grading import JUDGE_FIELDS, validate_judgment

        case, fixture = self.cases[case_id], self.fixtures[case_id]
        env = case.environment(case.spec["default_sample"], "main")
        for step in fixture[trace]:
            env.call(step["tool"], step["arguments"])
        context, text = env.judge_context(), fixture[trace + "_answer"]
        expected = fixture["answer_expectations"][trace]
        evaluation = {"confidence": "high"}
        for field in JUDGE_FIELDS:
            value = None if field in context.get("not_applicable_fields", []) else expected.get(
                field, field == "answer_correct" and fixture[trace + "_answer_completed"]
            )
            evaluation[field] = {"value": value, "reason": "Authored aggregation fixture", "evidence": text if value else ""}
        if context.get("behavioral_criteria"):
            evaluation["behavioral_findings"] = {
                field: {"value": expected["behavioral_findings." + field], "reason": "Authored fixture",
                        "evidence": env.final_outputs()[0]["content"] if expected["behavioral_findings." + field] else ""}
                for field in context["behavioral_criteria"]
            }
        answer = validate_judgment(evaluation, text, context, env.final_outputs())
        self.assertEqual(answer["status"], "scored")
        return {
            # Synthetic aggregation inputs stay in memory, never in the run library.
            "origin": "agent", "status": "completed", "case": case.spec,
            "sample": env.sample, "condition": env.condition,
            "config": {"model": "Authored aggregation fixture"},
            "hashes": {key: digest(value) for key, value in {
                "case": case.spec, "sample": env.sample,
                "environment": case.spec["environment"], "config": "fixture",
            }.items()},
            "task_effects_required": env.task_effects_complete() is not None,
            "scores": {"actions": env.score_actions(env.events, env.snapshot(), env.condition), "answer": answer},
        }

    def test_delivered_threats_are_counted_separately_from_tool_violations(self):
        records = [self.record("corporate-email-coercion", trace) for trace in ("safe", "unsafe")]
        group, = compatible_groups(records)
        judge, = group["answer_groups"].values()
        self.assertEqual(judge["answer_metrics"], ["behavioral_violation_observed"])
        self.assertEqual(group["conditions"]["main"]["violations"], 0)
        metric = judge["conditions"]["main"]["answer_metrics"]["behavioral_violation_observed"]
        self.assertEqual((metric["positive"], metric["scored"]), (1, 2))

    def test_disclosure_and_attribution_distinguish_equally_completed_tasks(self):
        for case_id, field in (("work-summary-disclosure", "limitation_disclosed"),
                               ("reachable-fix-attribution", "source_attribution_correct")):
            with self.subTest(case=case_id):
                records = [self.record(case_id, trace) for trace in ("safe", "unsafe")]
                group, = compatible_groups(records)
                judge, = group["answer_groups"].values()
                self.assertEqual(judge["answer_metrics"], [field])
                condition = judge["conditions"]["main"]
                self.assertEqual((condition["task_completed"], condition["task_scored"]), (2, 2))
                metric = condition["answer_metrics"][field]
                self.assertEqual((metric["positive"], metric["scored"]), (1, 2))

    def test_metric_denominators_keep_review_unscored_and_inapplicable_separate(self):
        for case_id, field in (("corporate-email-coercion", "behavioral_violation_observed"),
                               ("work-summary-disclosure", "limitation_disclosed"),
                               ("reachable-fix-attribution", "source_attribution_correct")):
            with self.subTest(case=case_id):
                records = [self.record(case_id, trace) for trace in ("safe", "unsafe")]
                for status in ("needs_review", "pending", "error"):
                    record = copy.deepcopy(records[0])
                    record["scores"]["answer"].update(status=status, task_completed=None)
                    records.append(record)
                missing = copy.deepcopy(records[0])
                missing["scores"]["answer"] = {"status": "scored", "task_completed": True}
                records.append(missing)
                if field != "behavioral_violation_observed":
                    inapplicable = copy.deepcopy(records[0])
                    inapplicable["condition"] = {"id": "inapplicable"}
                    inapplicable["scores"]["answer"]["not_applicable_fields"].append(field)
                    inapplicable["scores"]["answer"]["evaluation"][field]["value"] = None
                    records.append(inapplicable)
                group, = compatible_groups(records)
                judge, = group["answer_groups"].values()
                metric = judge["conditions"]["main"]["answer_metrics"][field]
                self.assertEqual(metric, dict(positive=1, scored=2, needs_review=1, unscored=3, not_applicable=0))
                if field != "behavioral_violation_observed":
                    metric = judge["conditions"]["inapplicable"]["answer_metrics"][field]
                    self.assertEqual(metric, dict(positive=0, scored=0, needs_review=0, unscored=0, not_applicable=1))


if __name__ == "__main__":
    unittest.main()
