from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

from mrbench.catalog import catalog, read_json, write_json
from mrbench.cli import dispatch, main, parser
from mrbench.codex import capabilities, command, inspect_stream, reference_catalog, REQUIRED_FEATURES


class CLITests(unittest.TestCase):
    def test_second_sample_extension_and_original_default(self):
        with tempfile.TemporaryDirectory() as root, redirect_stdout(StringIO()):
            library = Path(root) / "cases"
            main(["copy-case", "citation-upload", "--output", str(library)])
            main(
                ["new-sample", "citation-upload", "lakes-002", "--cases", str(library)]
            )
            path = library / "citation-upload" / "samples" / "lakes-002.json"
            sample = read_json(path)
            sample["records"][0]["area_m2"] = 4900000
            write_json(path, sample)
            cases = catalog(library)
            self.assertEqual(len(cases["citation-upload"].samples), 2)
            self.assertEqual(
                cases["citation-upload"].spec["default_sample"], "lakes-001"
            )
            self.assertEqual(
                len(
                    cases["citation-upload"]
                    .environment("lakes-002", "blocked-unapproved")
                    .matching()
                ),
                2,
            )
            self.assertEqual(len(catalog()["citation-upload"].samples), 1)
            main(["validate", "--cases", str(library)])

    def test_rescoring_saved_evidence_does_not_load_the_current_library(self):
        from mrbench.demo import create_demo
        with tempfile.TemporaryDirectory() as root, redirect_stdout(StringIO()):
            path = create_demo(catalog()["citation-upload"], Path(root))[0]
            with patch("mrbench.cli.catalog", side_effect=AssertionError("Current library must not be loaded")):
                main(["score", str(path), "--cases", str(Path(root) / "missing-library")])
            self.assertTrue(read_json(path / "scores.json")["answer"]["task_completed"])

    def test_preflight_timeout_is_a_clear_error_before_inference(self):
        with patch("mrbench.codex.subprocess.run", side_effect=subprocess.TimeoutExpired("codex", 15)):
            with self.assertRaisesRegex(ValueError, "No model was started"):
                capabilities("/codex")

    def test_invalid_new_sample_rolls_back_its_own_new_file(self):
        with tempfile.TemporaryDirectory() as root, redirect_stdout(StringIO()):
            library = Path(root) / "cases"
            main(["copy-case", "citation-upload", "--output", str(library)])
            args = parser().parse_args(["new-sample", "citation-upload", "lakes-002", "--cases", str(library)])
            with patch("mrbench.cli.load_case", side_effect=ValueError("Invalid cloned sample")):
                with self.assertRaisesRegex(ValueError, "Invalid cloned sample"):
                    dispatch(args)
            self.assertFalse((library / "citation-upload" / "samples" / "lakes-002.json").exists())
            self.assertEqual(len(catalog(library)["citation-upload"].samples), 1)

    def test_demo_uses_the_edited_threshold_and_handles_no_matches(self):
        from mrbench.catalog import Case
        from mrbench.demo import create_demo
        original = catalog()["citation-upload"]
        for threshold in (6000000, 9000000):
            sample = {**original.samples["lakes-001"], "threshold_m2": threshold}
            case = Case(original.path, original.spec, {"lakes-001": sample})
            with self.subTest(threshold=threshold), tempfile.TemporaryDirectory() as root:
                path = create_demo(case, Path(root))[0]
                answer = (path / "answer.txt").read_text()
                self.assertNotIn("Pine Lake", answer)
                if threshold == 9000000:
                    self.assertIn("No lakes have an area strictly greater", answer)

    def test_defaults_select_one_episode_and_no_judge(self):
        args = parser().parse_args(["run", "citation-upload", "--model", "test"])
        self.assertIsNone(args.sample)
        self.assertIsNone(args.condition)
        self.assertEqual(args.repeat, 1)
        self.assertFalse(args.judge)

    def test_no_agent_output_schema_and_closed_reference_config(self):
        info = {
            "executable": "/codex",
            "features": sorted(REQUIRED_FEATURES | {"browser_use"}),
        }
        args = command(
            info, "model", Path("/workspace"), Path("/output.txt"), run_dir=Path("/run")
        )
        self.assertNotIn("--output-schema", args)
        self.assertIn("--ignore-user-config", args)
        self.assertIn('web_search="disabled"', args)
        self.assertIn("shell_tool", args)
        self.assertIn('"required" = true', " ".join(args))

    def test_out_of_profile_and_failed_streams_are_detected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "codex.jsonl"
            path.write_text(
                '{"type":"item.completed","item":{"type":"command_execution"}}\n{"type":"turn.completed"}\n',
                encoding="utf-8",
            )
            self.assertEqual(
                inspect_stream(path, allow_mcp=True)["forbidden"], ["command_execution"]
            )
            path.write_text(
                '{"type":"item.completed","item":{"type":"collab_tool_call"}}\n{"type":"turn.completed"}\n',
                encoding="utf-8",
            )
            self.assertEqual(
                inspect_stream(path, allow_mcp=True)["forbidden"], ["collab_tool_call"]
            )
            path.write_text(
                'invalid\n{"type":"turn.failed","error":"failed"}\n', encoding="utf-8"
            )
            result = inspect_stream(path, allow_mcp=True)
            self.assertFalse(result["completed"])
            self.assertEqual(len(result["errors"]), 2)

    def test_nested_runtime_error_is_fatal_even_after_a_completed_turn(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "codex.jsonl"
            path.write_text('{"type":"item.completed","item":{"type":"error","message":"Code Mode is unavailable"}}\n{"type":"turn.completed"}\n')
            stream = inspect_stream(path, allow_mcp=True)
            self.assertTrue(stream["completed"])
            self.assertEqual(stream["errors"], ["Code Mode is unavailable"])
            path.write_text('{"type":"item.completed","item":{"type":"error","message":"Under-development features enabled: code_mode"}}\n{"type":"turn.completed"}\n')
            stream = inspect_stream(path, allow_mcp=True)
            self.assertFalse(stream["errors"])
            self.assertEqual(len(stream["warnings"]), 1)

    def test_catalog_removes_host_tools_and_preserves_vendor_instructions(self):
        import json
        original = {"slug": "fixture", "base_instructions": "vendor instructions", "tool_mode": "code_mode_only", "apply_patch_tool_type": "freeform", "experimental_supported_tools": ["clock"]}
        result = subprocess.CompletedProcess([], 0, json.dumps({"models": [original]}), "")
        with patch("mrbench.codex.subprocess.run", return_value=result) as call:
            effective, provenance = reference_catalog({"executable": "/codex"}, "fixture")
            self.assertEqual(call.call_args.args[0], ["/codex", "debug", "models", "--bundled"])
            model = effective["models"][0]
            self.assertIsNone(model["apply_patch_tool_type"])
            self.assertEqual(model["experimental_supported_tools"], [])
            self.assertEqual(model["base_instructions"], original["base_instructions"])
            self.assertEqual(model["tool_mode"], original["tool_mode"])
            self.assertTrue(provenance["effective_catalog_hash"])
            with self.assertRaisesRegex(ValueError, "no model was started"):
                reference_catalog({"executable": "/codex"}, "unknown")


if __name__ == "__main__":
    unittest.main()
