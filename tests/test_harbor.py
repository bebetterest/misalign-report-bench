from copy import deepcopy
import os
import shlex
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from mrbench import __version__
from mrbench.catalog import Case, catalog, digest, read_json, write_json
from mrbench.harbor_bridge import act, episode_identity, prepare_simulator, rewards, verify
from mrbench.harbor_export import export
from mrbench.harbor_metric import aggregate
from mrbench.runs import prepare
from mrbench.viewer import read_record, reproduction


class HarborTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = catalog()["citation-upload"]

    def test_export_preserves_prompts_and_separates_actor_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "dataset"
            tasks = export([self.case], root)
            self.assertEqual(len(tasks), 3)
            self.assertEqual(read_json(root / "main.job.json")["metrics"][0]["kwargs"], {
                "script_path": "metric.py",
            })
            self.assertEqual(sum(task["path"].startswith("main/") for task in tasks), 1)
            for entry in tasks:
                path = root / entry["path"]
                world = self.case.environment(entry["sample"], entry["condition"])
                self.assertEqual((path / "instruction.md").read_text(), world.prompt)
                actor = read_json(path / "environment/actor.json")
                self.assertEqual(actor["policy"], world.instructions)
                bundle = read_json(path / "environment/simulation/bundle.json")
                self.assertEqual(actor["input_hash"], digest(bundle))
                self.assertEqual(actor["prompt_hash"], digest(world.prompt))
                self.assertNotIn("prompt", actor)
                self.assertFalse((path / "tests").exists())
                config = tomllib.loads((path / "task.toml").read_text())
                self.assertEqual(config["metadata"]["condition_id"], entry["condition"])
                self.assertEqual(config["verifier"]["environment_mode"], "separate")
                self.assertEqual(config["artifacts"][0]["service"], "simulation")
                self.assertNotIn("simulation/", (path / "environment/Dockerfile").read_text())
            with self.assertRaisesRegex(ValueError, "new output directory"):
                export([self.case], root)

    def test_export_rejects_instructions_that_harbor_would_alter(self):
        sample = deepcopy(self.case.samples["lakes-001"])
        sample["task"] = "\n" + sample["task"]
        case = Case(self.case.path, self.case.spec, {sample["id"]: sample})
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "dataset"
            with self.assertRaisesRegex(ValueError, "Harbor would alter the instruction"):
                export([case], output)
            self.assertFalse(output.exists())

    def simulation(self, root):
        output = root / "dataset"
        row = next(row for row in export([self.case], output) if row["path"].startswith("main/"))
        task = output / row["path"]
        return task, read_json(task / "environment/simulation/bundle.json")

    def test_actor_detects_a_mixed_export_before_harness_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, bundle = self.simulation(root)
            task = read_json(path / "environment/actor.json")
            bundle["sample"]["records"][0]["area_m2"] += 1
            _, other = prepare_simulator(bundle, root / "simulator")
            client = httpx.Client(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=episode_identity(other)),
            ))
            with patch("mrbench.harbor_bridge.httpx.Client", return_value=client), patch(
                "mrbench.harbor_bridge.get_harness",
            ) as harness:
                with self.assertRaisesRegex(ValueError, "same Harbor export"):
                    act(task, root / "actor", "codex", "example", (path / "instruction.md").read_text(), "medium", 1, None)
                harness.assert_not_called()

    def capture_actor(self, actor, run, manifest):
        actor.mkdir()
        harness = {"id": "codex", "profile": "test-codex", "version": "fixture", "adapter_hash": "fixture"}
        world = self.case.environment("lakes-001", "blocked-unapproved")
        write_json(run / "mcp-ready.json", {"tools": [tool["name"] for tool in world.tools]})
        (actor / "answer.txt").write_text("The lake query is complete.")
        write_json(actor / "actor.json", {
            "episode": episode_identity(manifest), "prompt_hash": digest(world.prompt),
            "package_version": __version__, "origin": "protocol-check", "trial": 1,
            "config": {"model": "fixture", "backend": "harbor", "harness": harness,
                       "profile": harness["profile"], "max_calls": 40, "task_tool_policy": world.instructions},
            "execution": {"exit_code": 0},
            "stream": {"completed": True, "errors": [], "forbidden": []},
        })

    def test_verifier_detects_artifacts_from_another_repeat_of_the_same_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, bundle = self.simulation(root)
            run, manifest = prepare_simulator(bundle, root / "first")
            _, other = prepare_simulator(bundle, root / "second")
            self.assertEqual(episode_identity(manifest)["input_hash"], episode_identity(other)["input_hash"])
            self.capture_actor(root / "actor", run, manifest)
            with self.assertRaisesRegex(ValueError, "same episode"):
                verify(root / "second", root / "actor", root / "verifier")

    def test_missing_judge_key_preserves_completed_action_scores(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, bundle = self.simulation(root)
            run, manifest = prepare_simulator(bundle, root / "simulation")
            self.capture_actor(root / "actor", run, manifest)
            with patch.dict(os.environ, {"MRBENCH_JUDGE_MODEL": "judge", "MRBENCH_JUDGE_API_KEY": ""}), patch(
                "mrbench.harbor_bridge.judge",
            ) as judge:
                reward = verify(root / "simulation", root / "actor", root / "verifier")
                judge.assert_not_called()
            self.assertEqual(reward["valid_run"], 1)
            self.assertEqual(reward["violation_observed"], 0)
            self.assertEqual(reward["answer_unscored"], 1)
            self.assertNotIn("task_completed", reward)
            saved, scores = read_record(root / "verifier/record")
            self.assertEqual(saved["hashes"]["harbor_input"], digest(bundle))
            self.assertIsNone(reproduction(saved))
            self.assertEqual(scores["answer"]["status"], "error")

    def test_viewer_reproduction_uses_the_published_snapshot(self):
        sample = "lakes-001"
        condition = "available-unapproved"
        manifest = {
            "origin": "agent", "case": self.case.spec, "sample": {"id": sample},
            "condition": {"id": condition}, "harness": {"id": "grok"}, "trial": 2,
            "config": {"backend": "harbor", "model": "fixture"},
        }
        command = shlex.split(reproduction(manifest))
        self.assertEqual(command[:5], ["cd", "harbor-tasks", "&&", "uv", "run"])
        self.assertIn("harbor==0.25.0", command)
        self.assertEqual(command[command.index("-c") + 1], "controls.job.json")
        self.assertEqual(command[command.index("-i") + 1], f"citation-upload__{sample}__{condition}")
        self.assertEqual(command[command.index("--ae") + 1], "XAI_API_KEY=${XAI_API_KEY}")
        self.assertEqual(command[command.index("-o") + 1], "../runs/harbor")
        self.assertIn("trial=2", command)

    def test_missing_actor_preserves_evidence_without_issuing_scores(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            simulation = root / "simulation"
            prepare(self.case, "lakes-001", "blocked-unapproved", simulation, {"max_calls": 40})
            verifier = root / "verifier"
            self.assertEqual(verify(simulation, root / "absent", verifier), {
                "valid_run": 0, "answer_needs_review": 0, "answer_unscored": 1,
            })
            record = verifier / "record"
            self.assertEqual(read_record(record)[0]["status"], "invalid")
            self.assertIsNone(read_json(record / "scores.json")["task_completed"])

    def test_each_reward_uses_its_own_scored_denominator(self):
        action = {"status": "scored", "violation_attempted": False, "violation_observed": False}
        scored = rewards({"status": "completed"}, {
            "actions": action, "task_completed": True, "compliant_task_completed": True,
            "answer": {"status": "scored", "evaluation": {
                "limitation_disclosed": {"value": False}, "citation_complete": {"value": None},
            }},
        })
        review = rewards({"status": "completed"}, {
            "actions": action, "answer": {"status": "needs_review"},
        })
        values = aggregate([scored, review, None])
        self.assertEqual(values["task_completed"], 1)
        self.assertEqual(values["task_completed_n"], 1)
        self.assertEqual(values["limitation_disclosed"], 0)
        self.assertEqual(values["limitation_disclosed_n"], 1)
        self.assertEqual(values["violation_attempted_n"], 2)
        self.assertEqual(values["answer_unscored"], 2)
        self.assertEqual(values["answer_needs_review"], 1)
        self.assertNotIn("citation_complete", values)

    def test_incomplete_violations_are_separate_counts(self):
        answer = {"status": "pending"}
        clean = rewards({"status": "completed"}, {
            "actions": {"status": "scored", "violation_attempted": False, "violation_observed": False},
            "answer": answer,
        })
        incomplete = {"status": "timeout"}
        action = {"status": "observed_in_incomplete_run", "violation_attempted": True, "violation_observed": True}
        confirmed = rewards(incomplete, {"actions": action, "answer": answer})
        attempt = rewards(incomplete, {"actions": {**action, "violation_observed": False}, "answer": answer})
        unverified = rewards(incomplete, {"actions": {**action, "status": "unscored"}, "answer": answer})

        values = aggregate([clean, confirmed, attempt, unverified, None])
        self.assertEqual(values["trials"], 5)
        self.assertEqual(values["valid_runs"], 1)
        self.assertEqual((values["violation_observed"], values["violation_observed_n"]), (0, 1))
        self.assertEqual(values["incomplete_violations"], 1)
        self.assertEqual(values["incomplete_violation_attempts"], 2)
        self.assertNotIn("task_completed", values)
