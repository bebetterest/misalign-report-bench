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
        self.assertEqual(result["provider_count"], 2)
        self.assertEqual(result["source_count"], 27)
        self.assertEqual({provider["id"] for provider in result["providers"]}, {"openai", "transluce"})
        # A custom registry is honored without loading website discovery or a model.
        from mrbench.source_registry import SOURCE_INDEX
        custom = self.root / "local-sources.json"
        snapshot = read_json(SOURCE_INDEX.parent / "sources/openai.json")
        write_json(custom, snapshot)
        self.server.RequestHandlerClass.keywords["sources"] = custom
        result = self.client.get("/api/sources").json()
        self.assertEqual(result["provider_count"], 1)
        self.assertEqual(result["source_count"], 22)
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

    def test_comparisons_require_compatible_real_complete_scored_runs(self):
        template = read_json(self.paths[0] / "run.json")
        template["origin"] = "codex"
        template["scores"] = read_json(self.paths[0] / "scores.json")
        template["scores"]["answer"]["config_hash"] = "judge-a"
        pending = copy.deepcopy(template)
        pending["scores"]["answer"] = {
            "status": "pending",
            "task_completed": None,
            "config_hash": "judge-a",
        }
        different = copy.deepcopy(template)
        different["hashes"]["config"] = "different-model"
        different["hashes"]["comparison_config"] = "different-model"
        demo = copy.deepcopy(template)
        demo["origin"] = "demo"
        invalid = copy.deepcopy(template)
        invalid["status"] = "timeout"
        groups = compatible_groups([template, pending, different, demo, invalid])
        self.assertEqual(len(groups), 2)
        values = sorted(
            (next(iter(g["conditions"].values())) for g in groups),
            key=lambda x: x["runs"],
        )
        self.assertEqual(values[1]["runs"], 2)
        self.assertEqual(values[1]["answer_scored"], 1)
        self.assertEqual(values[1]["task_completed"], 1)

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


if __name__ == "__main__":
    unittest.main()
