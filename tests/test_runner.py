from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from mrbench.catalog import catalog, read_json
from mrbench.codex import execute
from mrbench.runs import run


class RunnerTests(unittest.TestCase):
    def setUp(self):
        catalog_patch = patch("mrbench.runs.reference_catalog", return_value=({"models": []}, {}))
        catalog_patch.start()
        self.addCleanup(catalog_patch.stop)

    def test_launch_failure_and_timeout_are_saved_as_incomplete(self):
        case = catalog()["citation-upload"]
        info = {"executable": "/missing/codex", "version": "fixture", "features": []}
        with tempfile.TemporaryDirectory() as root, redirect_stdout(StringIO()):
            path = run(
                case, "lakes-001", "blocked-unapproved", Path(root), info, "test"
            )
            self.assertEqual(read_json(path / "run.json")["status"], "invalid")
            self.assertEqual(
                read_json(path / "scores.json")["actions"]["status"],
                "observed_in_incomplete_run",
            )
            with patch(
                "mrbench.runs.command",
                return_value=[sys.executable, "-c", "import time; time.sleep(10)"],
            ):
                path = run(
                    case,
                    "lakes-001",
                    "blocked-unapproved",
                    Path(root),
                    info,
                    "test",
                    timeout=1,
                )
            self.assertEqual(read_json(path / "run.json")["status"], "timeout")
            self.assertIsNone(
                read_json(path / "scores.json")["compliant_task_completed"]
            )

    def test_completed_answer_without_mcp_is_invalid(self):
        case = catalog()["citation-upload"]
        info = {"executable": "/fixture", "version": "fixture", "features": []}

        def command(*args, **kwargs):
            output = args[3]
            script = f"from pathlib import Path; Path({str(output)!r}).write_text('natural answer'); print('{{\"type\":\"turn.completed\"}}')"
            return [sys.executable, "-c", script]

        with (
            tempfile.TemporaryDirectory() as root,
            redirect_stdout(StringIO()),
            patch("mrbench.runs.command", side_effect=command),
        ):
            path = run(
                case, "lakes-001", "blocked-unapproved", Path(root), info, "test"
            )
            self.assertEqual(read_json(path / "run.json")["status"], "invalid")


class RuntimeIsolationTests(unittest.TestCase):
    def test_child_runtime_is_clean_temporary_and_does_not_change_caller(self):
        import json
        import os

        before = os.environ.get("CODEX_HOME")
        before_path = os.environ.get("PATH")
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            prefix = root / "runtime-check"
            script = "import json,os; from pathlib import Path; p=Path(os.environ['CODEX_HOME']); print(json.dumps({'runtime':str(p),'agents':(p/'AGENTS.md').exists(),'skills':(p/'skills').exists(),'path':os.environ['PATH'].split(os.pathsep)[0]}))"
            result = execute([sys.executable, "-c", script], "", root, prefix, 5, code_mode_host=str(root / "bin/codex-code-mode-host"))
            self.assertEqual(result["exit_code"], 0)
            data = json.loads(prefix.with_suffix(".jsonl").read_text())
            self.assertFalse(data["agents"])
            self.assertFalse(data["skills"])
            self.assertEqual(data["path"], str(root / "bin"))
            self.assertFalse(Path(data["runtime"]).exists())
            self.assertEqual(os.environ.get("CODEX_HOME"), before)
            self.assertEqual(os.environ.get("PATH"), before_path)


if __name__ == "__main__":
    unittest.main()
