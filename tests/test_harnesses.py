"""Harness selection, native output validation and evidence boundaries."""

from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from mrbench.catalog import catalog, digest, read_json, write_json
from mrbench.cli import harness_config, parser
from mrbench.config import load_config
from mrbench.evidence import verify_input_hashes
from mrbench.harnesses import HarnessConfig, HarnessInfo, HarnessResult, get_harness, harness_metadata
from mrbench.harnesses.grok import ACTOR_KEY_ENV, GrokHarness, inspect_runtime, inspect_stream, runtime
from mrbench.runs import run
from mrbench.viewer import compatible_groups, details, export_run, reproduction


def native_events():
    return [
        {"type": "system", "subtype": "init", "permissionMode": "dontAsk", "tools": ["search_tool", "use_tool", "task__http_request"], "skills": [], "mcp_servers": [{"name": "task"}]},
        {"type": "assistant", "message": {"model": "grok-fixture-v1", "content": [
            {"type": "tool_use", "name": "use_tool", "input": {"tool_name": "task__http_request", "tool_input": {"method": "GET", "url": "https://lakes.test/map"}}},
        ]}},
        {"type": "assistant", "message": {"model": "grok-fixture-v1", "content": [{"type": "text", "text": "Natural answer"}]}},
        {"type": "result", "subtype": "success", "is_error": False, "stop_reason": "end_turn", "result": "Natural answer", "usage": {"input_tokens": 10}},
    ]


class GrokStreamTests(unittest.TestCase):
    def inspect(self, events):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "grok.jsonl"
            path.write_text("\n".join(json.dumps(event) for event in events))
            return inspect_stream(path, ("http_request",))

    def test_native_messages_keep_answer_usage_and_returned_identity(self):
        result = self.inspect(native_events())
        self.assertTrue(result["completed"])
        self.assertFalse(result["errors"] + result["forbidden"])
        self.assertEqual(result["answer"], "Natural answer")
        self.assertEqual(result["response_models"], ["grok-fixture-v1"])

    def test_failures_truncation_unexpected_tools_and_host_input_are_rejected(self):
        fixtures = []
        events = native_events(); events.pop(); fixtures.append(events)
        events = native_events(); events[-1]["stop_reason"] = "max_tokens"; fixtures.append(events)
        events = native_events(); events[-1]["is_error"] = True; fixtures.append(events)
        events = native_events(); events[0]["tools"].append("bash"); fixtures.append(events)
        events = native_events(); events[0]["skills"].append("personal"); fixtures.append(events)
        events = native_events(); events[1]["parent_tool_use_id"] = "subagent"; fixtures.append(events)
        events = native_events(); events[1]["message"]["content"][0]["input"] = {"tool_name": "task__http_request", "tool_input_file": "/host/file"}; fixtures.append(events)
        events = native_events(); events[1]["message"]["content"][0]["input"]["tool_name"] = "personal__secret"; fixtures.append(events)
        events = native_events(); events.append({"type": "assistant", "message": {"content": []}}); fixtures.append(events)
        events = native_events(); events.insert(2, {"type": "error", "message": "Nested failure"}); fixtures.append(events)
        events = native_events(); events[1]["message"]["content"] = [None]; fixtures.append(events)
        events = native_events(); events[0]["tools"] = []; fixtures.append(events)
        events = native_events(); events[0]["permissionMode"] = "bypassPermissions"; fixtures.append(events)
        events = native_events(); events.insert(2, {"type": "system", "subtype": "error"}); fixtures.append(events)
        events = native_events(); events[-1]["usage"] = {"server_tool_use": {"web_search_requests": 1}}; fixtures.append(events)
        events = native_events(); events[1]["message"]["content"] = [{"type": "server_tool_use"}]; fixtures.append(events)
        for events in fixtures:
            with self.subTest(events=events):
                result = self.inspect(events)
                self.assertTrue(not result["completed"] or result["errors"] or result["forbidden"])

    def test_invalid_native_json_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "grok.jsonl"
            path.write_text('{"type":')
            self.assertTrue(inspect_stream(path, ())["errors"])


class HarnessConfigurationTests(unittest.TestCase):
    def test_selection_and_legacy_executable_override(self):
        default = parser().parse_args(["run", "citation-upload", "--model", "fixture"])
        self.assertEqual(default.harness, "codex")
        self.assertEqual(harness_config(default).model, "fixture")
        bad = parser().parse_args(["doctor", "--harness", "grok", "--codex", "/codex"])
        with self.assertRaisesRegex(ValueError, "Codex"):
            harness_config(bad)
        with self.assertRaisesRegex(ValueError, "Unknown harness"):
            get_harness("other")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.toml"
            path.write_text('[harness.grok]\nexecutable="/grok"\nmax_turns=12\n')
            self.assertEqual(load_config(path)["harness"]["grok"]["max_turns"], 12)
            args = parser().parse_args(["doctor", "--harness", "grok", "--config", str(path)])
            self.assertEqual(harness_config(args).executable, "/grok")
            for invalid in ('[harness.other]', 'harness=42', '[harness.codex]\nbase_url="https://actor.test"', '[harness.grok]\nexecutable=42'):
                path.write_text(invalid)
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    load_config(path)

    def test_bad_grok_options_fail_before_a_native_process(self):
        for options in ({"typo": True}, {"api_key_env": 42}, {"api_backend": "unknown"}, {"base_url": "https://secret:key@actor.test"}, {"base_url": "https://actor.test/path with spaces"}, {"max_turns": True}, {"max_output_tokens": 1}):
            with self.subTest(options=options), patch("mrbench.harnesses.grok.subprocess.run") as native:
                with self.assertRaises(ValueError):
                    GrokHarness().preflight(HarnessConfig(options=options))
                native.assert_not_called()

    def test_unsupported_or_stalled_cli_fails_during_preflight(self):
        results = [subprocess.CompletedProcess([], 0, "grok fixture", ""), subprocess.CompletedProcess([], 0, "old CLI help", "")]
        with patch("mrbench.harnesses.grok.shutil.which", return_value="/fixture/grok"), patch("mrbench.harnesses.grok.subprocess.run", side_effect=results) as native:
            with self.assertRaisesRegex(ValueError, "closed reference profile"):
                GrokHarness().preflight(HarnessConfig())
            self.assertEqual(native.call_count, 2)
        with patch("mrbench.harnesses.grok.shutil.which", return_value="/fixture/grok"), patch("mrbench.harnesses.grok.subprocess.run", side_effect=subprocess.TimeoutExpired("grok", 15)):
            with self.assertRaisesRegex(ValueError, "timed out"):
                GrokHarness().preflight(HarnessConfig())

    def test_runtime_is_temporary_auth_only_and_ignores_caller_overrides(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root)
            (source / "auth.json").write_text('{"fixture":"auth"}')
            (source / "AGENTS.md").write_text("personal instructions")
            before = {"GROK_HOME": str(source), "GROK_CONFIG": "personal", "XAI_BASE_URL": "https://wrong.test", "MRBENCH_PROTOCOL_KEY": "dummy"}
            with patch.dict(os.environ, before):
                config = HarnessConfig(model="fixture")
                with runtime(config) as (home, workspace, environment, settings):
                    self.assertTrue((home / "auth.json").is_file())
                    self.assertEqual((home / "auth.json").stat().st_mode & 0o777, 0o600)
                    self.assertFalse((home / "AGENTS.md").exists())
                    self.assertNotIn("GROK_CONFIG", environment)
                    self.assertNotIn("XAI_BASE_URL", environment)
                    self.assertFalse(workspace.is_relative_to(Path.cwd()))
                    self.assertEqual(settings["skills"]["ignore"], [str(Path.home())])
                self.assertFalse(home.exists())
                self.assertEqual(os.environ["GROK_HOME"], str(source))
                with runtime(HarnessConfig(use_auth=False)) as (home, _, _, _):
                    self.assertFalse((home / "auth.json").exists())
                config = HarnessConfig(model="fixture", options={"base_url": "http://127.0.0.1:1234/v1", "api_key_env": "MRBENCH_PROTOCOL_KEY"})
                with runtime(config) as (home, _, environment, settings):
                    self.assertFalse((home / "auth.json").exists())
                    self.assertNotIn("MRBENCH_PROTOCOL_KEY", environment)
                    self.assertNotIn("XAI_API_KEY", environment)
                    self.assertEqual(environment[ACTOR_KEY_ENV], "dummy")
                    self.assertEqual(settings["model"]["fixture"]["env_key"], ACTOR_KEY_ENV)

    def test_native_inspection_fails_on_personal_context_or_ignored_configuration(self):
        report = {name: [] for name in ("projectInstructions", "hooks", "skills", "plugins", "lspServers", "agents", "mcpServers", "configWarnings")}
        report.update(configSources={"layers": [{"path": "/runtime/config.toml"}]}, grokVersion="fixture")
        for changes in ({"skills": [{"name": "personal"}]}, {"hooks": [None]}, {"configWarnings": ["ignored setting"]}, {"mcpServers": [{"name": "personal"}]}, {"configSources": {"layers": [{"path": "/caller/config.toml"}]}}):
            result = subprocess.CompletedProcess([], 0, json.dumps(report | changes), "")
            with patch("mrbench.harnesses.grok.subprocess.run", return_value=result), self.assertRaises(ValueError):
                inspect_runtime("/grok", Path("/workspace"), {"GROK_HOME": "/runtime"}, ())


class GenericRunnerTests(unittest.TestCase):
    def test_adapter_setup_failure_is_preserved_as_invalid_evidence(self):
        class FailedAdapter:
            evidence_modules = ("mrbench.harnesses.base",)

            def run(self, episode):
                raise ValueError("Unexpected personal context")

        info = HarnessInfo("grok", "fixture-cli", "fixture-profile", "/grok", {})
        with tempfile.TemporaryDirectory() as root, redirect_stdout(StringIO()), patch("mrbench.runs.get_harness", return_value=FailedAdapter()):
            path = run(catalog()["citation-upload"], "lakes-001", "blocked-unapproved", Path(root), info, "fixture")
            self.assertEqual(read_json(path / "run.json")["status"], "invalid")
            self.assertIn("personal context", read_json(path / "run.json")["execution"]["error"])
            self.assertIsNone(read_json(path / "scores.json")["compliant_task_completed"])

    def test_record_evidence_export_and_legacy_interpretation(self):
        class FixtureAdapter:
            evidence_modules = ("mrbench.harnesses.base",)

            def run(self, episode):
                write_json(episode.run_dir / "mcp-ready.json", {"fixture": True})
                write_json(episode.run_dir / "harness-config.json", {"tools": "task only"})
                (episode.run_dir / "grok.jsonl").write_text("native fixture")
                return HarnessResult({"exit_code": 0, "timed_out": False}, {"completed": True, "errors": [], "forbidden": [], "response_models": ["fixture-v1"]}, "Natural answer")

        info = HarnessInfo("grok", "fixture-cli", "fixture-profile", "/grok", {})
        with tempfile.TemporaryDirectory() as root, redirect_stdout(StringIO()), patch("mrbench.runs.get_harness", return_value=FixtureAdapter()):
            root = Path(root)
            case = catalog()["citation-upload"]
            path = run(case, "lakes-001", "blocked-unapproved", root, info, "fixture")
            manifest = read_json(path / "run.json")
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(manifest["origin"], "agent")
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["harness"]["id"], "grok")
            verify_input_hashes(manifest, path)
            self.assertEqual(details(root, path.name)["native_stream"]["text"], "native fixture")
            self.assertIn("--harness grok", reproduction(manifest))
            import io, zipfile
            with zipfile.ZipFile(io.BytesIO(export_run(root, path.name))) as archive:
                self.assertIn("harness-config.json", archive.namelist())
                self.assertIn("grok.jsonl", archive.namelist())
            write_json(path / "harness-config.json", {"tools": "tampered"})
            with self.assertRaisesRegex(ValueError, "harness artifact"):
                verify_input_hashes(manifest, path)
            old = {"origin": "codex", "config": {"codex_version": "old"}, "profile": "old-profile"}
            self.assertEqual(harness_metadata(old), {"id": "codex", "version": "old", "profile": "old-profile"})
            changed = deepcopy(manifest); changed["harness"]["version"] = "other"
            with self.assertRaisesRegex(ValueError, "harness"):
                verify_input_hashes(changed)

    def test_comparisons_separate_harness_and_returned_model(self):
        record = {
            "origin": "agent", "status": "completed", "case": {"id": "case", "version": "1"},
            "sample": {"id": "sample", "version": "1"}, "condition": {"id": "main"},
            "config": {"model": "alias"}, "hashes": dict.fromkeys(("case", "sample", "environment", "config"), "same"),
            "harness": {"id": "grok", "version": "1", "profile": "closed", "adapter_hash": "same"},
            "stream": {"response_models": ["grok-v1"]},
            "scores": {"actions": {"status": "scored", "violation_observed": False, "violation_attempted": False}},
        }
        other = deepcopy(record); other["harness"]["id"] = "codex"
        version = deepcopy(record); version["stream"]["response_models"] = ["grok-v2"]
        protocol = deepcopy(record); protocol["origin"] = "protocol-check"
        groups = compatible_groups([record, other, version, protocol])
        self.assertEqual(len(groups), 3)
        self.assertEqual(sum(g["conditions"]["main"]["runs"] for g in groups), 3)


if __name__ == "__main__":
    unittest.main()
