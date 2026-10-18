"""Verify saved inputs and evidence without executing an environment or a model."""

import json

from .catalog import comparison_config, digest


def task_completion(answer, actions, requires_effects=False):
    if (
        answer.get("status") != "scored"
        or type(answer.get("task_completed")) is not bool
    ):
        return None
    if not answer["task_completed"]:
        return False
    if requires_effects:
        if (
            actions.get("status") != "scored"
            or type(actions.get("task_effects_complete")) is not bool
        ):
            return None
        return actions["task_effects_complete"]
    return True


def local_text(path):
    if path.is_symlink():
        raise ValueError("Linked artifacts cannot be verified")
    return path.read_text(encoding="utf-8")


def verify_input_hashes(manifest, run_dir=None):
    hashes = manifest["hashes"]
    for key in ("case", "sample", "config"):
        if digest(manifest[key]) != hashes[key]:
            raise ValueError(f"Saved {key} differs from its recorded input hash")
    if (
        "comparison_config" in hashes
        and digest(comparison_config(manifest["config"])) != hashes["comparison_config"]
    ):
        raise ValueError("Saved comparison config differs from its recorded hash")
    if "task_effects_required" in hashes and (
        type(manifest.get("task_effects_required")) is not bool
        or digest(manifest["task_effects_required"]) != hashes["task_effects_required"]
    ):
        raise ValueError("Saved task effect requirement differs from its recorded hash")
    conditions = manifest["case"]["conditions"]
    if manifest["condition"] not in conditions:
        raise ValueError("Saved condition differs from its case definition")
    if run_dir is not None and "prompt" in hashes:
        if digest(local_text(run_dir / "prompt.txt")) != hashes["prompt"]:
            raise ValueError("Saved task differs from its recorded input hash")
    catalog = manifest["config"].get("model_catalog")
    if run_dir is not None and catalog:
        if (
            digest(json.loads(local_text(run_dir / "model-catalog.json")))
            != catalog["effective_catalog_hash"]
        ):
            raise ValueError(
                "Saved model catalog differs from the reference configuration"
            )


def load_action_evidence(run_dir):
    events = [
        json.loads(line) for line in local_text(run_dir / "events.jsonl").splitlines()
    ]
    previous = None
    for number, event in enumerate(events, 1):
        if not isinstance(event, dict):
            raise ValueError("Event evidence must contain objects")
        unhashed = {key: value for key, value in event.items() if key != "hash"}
        if (
            type(event["seq"]) is not int
            or event["seq"] != number
            or event["previous_hash"] != previous
            or digest(unhashed) != event["hash"]
        ):
            raise ValueError("Event evidence is truncated or inconsistent")
        previous = event["hash"]
    envelope = json.loads(local_text(run_dir / "state.json"))
    if (
        not isinstance(envelope, dict)
        or not isinstance(envelope.get("world"), dict)
        or type(envelope["event_count"]) is not int
        or envelope["event_count"] != len(events)
        or envelope["last_event_hash"] != previous
        or digest(envelope["world"]) != envelope["world_hash"]
    ):
        raise ValueError("State snapshot and event evidence disagree")
    hashes = {
        key: envelope[key] for key in ("event_count", "last_event_hash", "world_hash")
    }
    return events, envelope["world"], hashes


def validate_task_outputs(outputs, requirements):
    if (
        not isinstance(outputs, dict)
        or outputs.get("schema_version") != 1
        or not isinstance(outputs.get("items"), list)
        or len(outputs["items"]) != len(requirements)
    ):
        raise ValueError("Final task texts have an invalid artifact structure")
    for item, requirement in zip(outputs["items"], requirements):
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "label", "content"}
            or item.get("id") != requirement["id"]
            or item.get("label") != requirement["label"]
            or item["content"] is not None
            and not isinstance(item["content"], str)
        ):
            raise ValueError(
                "Final task texts do not match their declared text selectors"
            )


def answer_evidence_hashes(run_dir, manifest):
    hashes = {"answer": digest(local_text(run_dir / "answer.txt"))}
    recorded = manifest["hashes"]
    if "judge_context" in recorded:
        context = json.loads(local_text(run_dir / "judge-context.json"))
        hashes["judge_context"] = digest(context)
        if context.get("output_requirements"):
            outputs = json.loads(local_text(run_dir / "task-outputs.json"))
            validate_task_outputs(outputs, context["output_requirements"])
            if (
                outputs.get("schema_version") != 1
                or outputs.get("requirements_hash")
                != digest(context["output_requirements"])
                or "task_outputs" not in recorded
                or "task_output_state" not in recorded
            ):
                raise ValueError(
                    "Final task texts are missing their recorded evidence binding"
                )
            _, _, state_hashes = load_action_evidence(run_dir)
            if outputs["source_world_hash"] != state_hashes["world_hash"]:
                raise ValueError("Final task texts belong to a different final state")
            hashes["task_outputs"] = digest(outputs)
            hashes["task_output_state"] = state_hashes["world_hash"]
    for key, value in hashes.items():
        if key in recorded and recorded[key] != value:
            raise ValueError(f"Saved {key} changed; use the original recorded evidence")
    return hashes


def verify_answer_score(run_dir, manifest, score):
    if score.get("status") not in ("scored", "needs_review"):
        return
    if score["status"] == "scored" and not isinstance(
        score.get("task_completed"), bool
    ):
        raise ValueError("Stored answer grade requires boolean task completion")
    if score["status"] == "needs_review" and score.get("task_completed") is not None:
        raise ValueError("Review-required grades cannot establish task completion")
    verify_input_hashes(manifest, run_dir)
    actual = answer_evidence_hashes(run_dir, manifest)
    recorded = score.get("evidence_hashes")
    if recorded is None:
        # Older real runs bind these artifacts in their manifest. Unbound preset
        # grades need an explicit new judgment; they cannot establish completion.
        if "answer" not in manifest["hashes"]:
            raise ValueError(
                "Stored answer grade has no evidence binding; judge the recorded answer again"
            )
        recorded = {key: manifest["hashes"][key] for key in actual}
    if recorded != actual:
        raise ValueError("Stored answer grade belongs to different answer evidence")
