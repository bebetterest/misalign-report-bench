"""Run artifacts are ordinary files; each episode receives a fresh, independent world."""

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import uuid

from . import __version__
from .catalog import BUILTIN_CASES, comparison_config, digest, read_json, write_json
from .harnesses import Episode, HarnessInfo, HarnessResult, get_harness
from .harnesses.base import configuration_artifact
from .grading import save_scores
from .environment import implementation_source


def prepare(case, sample_id, condition_id, root, config, origin="codex", trial=1, *, harness=None):
    environment = case.environment(sample_id, condition_id)
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    run_dir = (root / run_id).resolve()
    run_dir.mkdir(parents=True)
    (run_dir / "workspace").mkdir()
    environment.max_calls = config["max_calls"]
    implementation = implementation_source(environment)
    context = environment.judge_context()
    framework = {
        name: (Path(__file__).parent / name).read_text(encoding="utf-8")
        for name in (
            "environment.py",
            "harnesses/base.py",
            "runs.py",
            "mcp_server.py",
            "grading.py",
            "evidence.py",
            "catalog.py",
            "config.py",
            "outputs.py",
        )
    }
    if harness:
        profile = harness["profile"]
    elif origin in ("codex", "codex-smoke"):
        profile = config.get("profile", "legacy-codex")
    else:
        profile = {
            "judge-check": "answer-judge-reference-v1",
            "environment-check": "scripted-environment-v1",
        }.get(origin, "scripted-demo")
    manifest = {
        "schema_version": 2 if harness else 1,
        "id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "origin": origin,
        "package_version": __version__,
        "trial": trial,
        "case": case.spec,
        "sample": case.samples[sample_id],
        "condition": case.condition(condition_id),
        "case_library": str(case.path.parent)
        if case.path.parent != BUILTIN_CASES.resolve()
        else None,
        "config": config,
        "task_effects_required": environment.task_effects_complete() is not None,
        "hashes": {
            "case": digest(case.spec),
            "sample": digest(case.samples[sample_id]),
            "environment": digest(implementation),
            "framework": digest(framework),
            "judge_context": digest(context),
            "prompt": digest(environment.prompt),
            "config": digest(config),
            "comparison_config": digest(comparison_config(config)),
            "task_effects_required": digest(environment.task_effects_complete() is not None),
        },
        "profile": profile,
    }
    if harness:
        manifest["harness"] = harness
        manifest["hashes"]["harness"] = digest(harness)
    write_json(run_dir / "run.json", manifest)
    (run_dir / "prompt.txt").write_text(environment.prompt, encoding="utf-8")
    write_json(run_dir / "judge-context.json", context)
    environment.persist(run_dir)
    return run_dir, manifest, environment


def run(
    case,
    sample_id,
    condition_id,
    root,
    info,
    model,
    timeout=180,
    max_calls=40,
    effort="medium",
    trial=1,
    *,
    origin="agent",
):
    """Execute a preflighted harness against one independently recorded episode."""
    if not isinstance(info, HarnessInfo):
        raise ValueError("Run requires HarnessInfo from the selected adapter's preflight")
    adapter = get_harness(info.id)
    metadata = info.metadata(adapter)
    for name, value in info.artifacts.items():
        if not configuration_artifact(name) or name == "command.json":
            raise ValueError("Unsupported harness configuration artifact")
        digest(value)
    environment = case.environment(sample_id, condition_id)
    config = {
        **info.settings,
        "model": model,
        "harness": metadata,
        "harness_executable": info.executable,
        "timeout": timeout,
        "max_calls": max_calls,
        "effort": effort,
        "profile": info.profile,
        "task_tool_policy": environment.instructions,
    }
    run_dir, manifest, _ = prepare(
        case, sample_id, condition_id, root, config, origin=origin, trial=trial,
        harness=metadata,
    )
    for name, value in info.artifacts.items():
        write_json(run_dir / name, value)
    episode = Episode(
        run_dir, run_dir / "workspace", environment.prompt, environment.instructions,
        model, timeout, max_calls, effort,
        tuple(tool["name"] for tool in environment.tools), info,
    )
    print(
        f"Running {info.id}: {case.id}/{sample_id}/{condition_id}, trial {trial} → {run_dir.name}",
        flush=True,
    )
    try:
        result = adapter.run(episode)
        if not isinstance(result, HarnessResult):
            raise ValueError("Adapter must return HarnessResult")
        outcome, stream = result.execution, result.stream
        if (
            type(outcome.get("exit_code")) is not int
            or type(stream.get("completed")) is not bool
            or any(not isinstance(stream.get(key), list) for key in ("errors", "forbidden"))
        ):
            raise ValueError("Adapter returned invalid execution/stream diagnostics")
        if result.answer is not None:
            if not isinstance(result.answer, str):
                raise ValueError("Harness final answer must be text")
            (run_dir / "answer.txt").write_text(result.answer, encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        outcome = {"exit_code": -1, "timed_out": False, "error": str(exc)}
        stream = {"completed": False, "errors": [str(exc)], "forbidden": []}
    answer_path = run_dir / "answer.txt"
    valid = (
        not outcome["exit_code"]
        and stream["completed"]
        and not stream["errors"]
        and not stream["forbidden"]
        and not (run_dir / "budget-exhausted.json").exists()
        and (run_dir / "mcp-ready.json").exists()
        and answer_path.exists()
        and bool(answer_path.read_text(encoding="utf-8").strip())
    )
    manifest.update(
        {
            "status": "completed"
            if valid
            else "timeout"
            if outcome.get("timed_out")
            else "interrupted"
            if outcome.get("interrupted")
            else "invalid",
            "execution": outcome,
            "stream": stream,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if answer_path.exists():
        manifest["hashes"]["answer"] = digest(answer_path.read_text(encoding="utf-8"))
    artifacts = {}
    for path in run_dir.iterdir():
        if path.is_file() and configuration_artifact(path.name):
            artifacts[path.name] = digest(read_json(path))
    manifest["harness_artifacts"] = artifacts
    manifest["hashes"]["harness_artifacts"] = digest(artifacts)
    if not valid:
        manifest["validation_error"] = (
            "The harness must finish with a nonblank answer, initialized task MCP, "
            "valid native output and no tools outside its reference profile. "
            "Inspect the execution diagnostics and native stderr log."
        )
    write_json(run_dir / "run.json", manifest)
    save_scores(run_dir)
    return run_dir
