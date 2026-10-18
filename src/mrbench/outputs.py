"""Freeze only final task deliverables, never an action trace or service state.

The trusted case declares output selectors. Extraction is bound to the recorded
environment implementation and state; later judging reuses the frozen texts.
"""

from .catalog import Case, digest, read_json, write_json
from .environment import implementation_source
from .evidence import load_action_evidence, verify_input_hashes, validate_task_outputs


def freeze_outputs(run_dir, manifest):
    if "judge_context" not in manifest["hashes"]:
        return manifest
    context = read_json(run_dir / "judge-context.json")
    requirements = context.get("output_requirements", [])
    if not requirements or manifest["status"] != "completed":
        return manifest
    verify_input_hashes(manifest, run_dir)
    if digest(context) != manifest["hashes"]["judge_context"]:
        raise ValueError("Task output requirements differ from the recorded context")
    target = run_dir / "task-outputs.json"
    if "task_outputs" in manifest["hashes"]:
        # Verification and re-grading must never replace the original output set.
        return manifest
    if target.exists() or target.is_symlink():
        raise ValueError(
            "Unbound task output artifact exists; restore the recorded evidence"
        )
    case = Case(
        run_dir, manifest["case"], {manifest["sample"]["id"]: manifest["sample"]}
    )
    environment = case.environment(
        manifest["sample"]["id"], manifest["condition"]["id"]
    )
    if digest(implementation_source(environment)) != manifest["hashes"]["environment"]:
        raise ValueError(
            "Restore the recorded environment before extracting task outputs"
        )
    _, world, evidence = load_action_evidence(run_dir)
    items = environment.final_outputs(world)
    expected_ids = [item["id"] for item in requirements]
    if (
        not isinstance(items, list)
        or any(not isinstance(item, dict) for item in items)
        or [item.get("id") for item in items] != expected_ids
    ):
        raise ValueError(
            "Final task outputs must match the trusted output requirements"
        )
    if any(
        set(item) != {"id", "label", "content"}
        or not isinstance(item["label"], str)
        or item["content"] is not None
        and not isinstance(item["content"], str)
        for item in items
    ):
        raise ValueError("Task outputs must contain only declared text deliverables")
    value = {
        "schema_version": 1,
        "requirements_hash": digest(requirements),
        "source_world_hash": evidence["world_hash"],
        "items": items,
    }
    validate_task_outputs(value, requirements)
    write_json(target, value)
    manifest["hashes"]["task_outputs"] = digest(value)
    manifest["hashes"]["task_output_state"] = evidence["world_hash"]
    write_json(run_dir / "run.json", manifest)
    return manifest
