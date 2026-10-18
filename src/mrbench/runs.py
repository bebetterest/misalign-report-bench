"""Run artifacts are ordinary files; each episode receives a fresh, independent world."""

from datetime import datetime, timezone
from pathlib import Path
import uuid

from . import __version__
from .catalog import BUILTIN_CASES, comparison_config, digest, write_json
from .codex import command, execute, inspect_stream, reference_catalog, PROFILE_VERSION
from .grading import save_scores
from .environment import implementation_source


def prepare(case, sample_id, condition_id, root, config, origin="codex", trial=1):
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
        name: Path(__file__).with_name(name).read_text(encoding="utf-8")
        for name in (
            "environment.py",
            "codex.py",
            "runs.py",
            "mcp_server.py",
            "grading.py",
            "evidence.py",
            "catalog.py",
            "config.py",
            "outputs.py",
        )
    }
    manifest = {
        "schema_version": 1,
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
        "profile": PROFILE_VERSION
        if origin in ("codex", "codex-smoke")
        else "answer-judge-reference-v1" if origin == "judge-check"
        else "scripted-environment-v1" if origin == "environment-check" else "scripted-demo",
    }
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
    origin="codex",
):
    from .codex import DISABLED_FEATURES

    model_catalog, catalog_info = reference_catalog(info, model)
    config = {
        "model": model,
        "codex_version": info["version"],
        "codex_executable": info["executable"],
        "code_mode_host": info.get("code_mode_host"),
        "model_catalog": catalog_info,
        "timeout": timeout,
        "max_calls": max_calls,
        "effort": effort,
        "profile": PROFILE_VERSION,
        "disabled_features": sorted(DISABLED_FEATURES.intersection(info["features"])),
        "context_guard": info.get("context_guard", "isolated temporary runtime"),
        "task_tool_policy": case.environment(sample_id, condition_id).instructions,
        "provider_config": info.get("provider_config", {}),
    }
    run_dir, manifest, _ = prepare(
        case, sample_id, condition_id, root, config, origin=origin, trial=trial
    )
    write_json(run_dir / "model-catalog.json", model_catalog)
    workspace = run_dir / "workspace"
    args = command(
        info, model, workspace, run_dir / "answer.txt", run_dir=run_dir, effort=effort,
        task_instructions=config["task_tool_policy"],
    )
    write_json(run_dir / "command.json", {"argv": args})
    print(
        f"Running {case.id}/{sample_id}/{condition_id}, trial {trial} → {run_dir.name}",
        flush=True,
    )
    outcome = execute(
        args,
        (run_dir / "prompt.txt").read_text(encoding="utf-8"),
        workspace,
        run_dir / "codex",
        timeout,
        code_mode_host=info.get("code_mode_host"),
    )
    stream = inspect_stream(run_dir / "codex.jsonl", allow_mcp=True)
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
            if outcome["timed_out"]
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
    if not valid:
        manifest["validation_error"] = (
            "Codex must complete with an answer, initialized benchmark MCP, valid JSONL, and no tools outside the reference profile. Inspect codex.stderr.log for startup/auth/config failures."
        )
    write_json(run_dir / "run.json", manifest)
    save_scores(run_dir)
    return run_dir
