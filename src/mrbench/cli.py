"""The public CLI; a configured API judge is opt-in, separate from agent execution."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import sys
import uuid

from .catalog import catalog, identifier, load_case, read_json, write_json
from .config import JudgeConfig, load_config, judge_api_key


def common(parser, *, child=False):
    default = argparse.SUPPRESS if child else None
    parser.add_argument(
        "--sources",
        type=Path,
        default=default,
        help="Alternative source registry JSON (default: packaged websites)",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=default,
        help="Alternative case library (default: packaged cases)",
    )
    parser.add_argument(
        "--runs",
        type=Path,
        default=argparse.SUPPRESS if child else Path("runs"),
        help="Local run directory",
    )
    parser.add_argument(
        "--config", type=Path, default=default, help="TOML config containing [judge]"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=default,
        help="Read judge credentials from this literal KEY=value file; not passed to Codex",
    )


def positive(value):
    number = int(value)
    if not 1 <= number <= 600:
        raise argparse.ArgumentTypeError("Use an integer between 1 and 600")
    return number


def parser():
    root = argparse.ArgumentParser(
        prog="mrbench",
        description="Public reports → reproducible environments → Codex → evidence",
    )
    common(root)
    sub = root.add_subparsers(dest="command", required=True)
    for name, help_text in [
        ("list", "List cases and sample counts"),
        ("validate", "Validate the case library without a model"),
        ("doctor", "Check Codex capabilities and judge configuration"),
        ("coverage", "Inspect the dated public-report and notice coverage map"),
    ]:
        item = sub.add_parser(name, help=help_text)
        common(item, child=True)
        if name == "doctor":
            item.add_argument("--codex")
    sources = sub.add_parser(
        "sources",
        help="List source websites or explicitly check their public indexes for updates",
    )
    common(sources, child=True)
    source_commands = sources.add_subparsers(dest="source_command", required=True)
    for name in ("list", "check"):
        item = source_commands.add_parser(name)
        common(item, child=True)
        if name == "check":
            item.add_argument("--provider", default="all", help="Website id, or all")
            item.add_argument(
                "--content",
                action="store_true",
                help="Also compare article text hashes; may report upstream access errors",
            )
            item.add_argument("--timeout", type=positive, default=30)
            item.add_argument(
                "--output",
                type=Path,
                help="New JSON review report; never changes registered snapshots",
            )
    show = sub.add_parser("show", help="Inspect a case, task, conditions and rubric")
    common(show, child=True)
    show.add_argument("case")
    show.add_argument("--sample")
    run = sub.add_parser("run", help="Run the actual Codex CLI in a fresh task world")
    common(run, child=True)
    run.add_argument("case")
    run.add_argument("--model", required=True)
    run.add_argument("--sample", help="Sample id or all; default: the case default")
    run.add_argument(
        "--condition", help="Condition id or all; default: the main condition"
    )
    run.add_argument("--repeat", type=positive, default=1)
    run.add_argument("--timeout", type=positive, default=180)
    run.add_argument("--max-calls", type=positive, default=40)
    run.add_argument("--effort", choices=["low", "medium", "high"], default="medium")
    run.add_argument("--codex")
    run.add_argument(
        "--judge",
        action="store_true",
        help="Also call the configured answer judge once per completed run",
    )
    run.add_argument("--judge-model")
    score = sub.add_parser(
        "score", help="Re-score saved evidence without re-running the agent"
    )
    common(score, child=True)
    score.add_argument("run", help="Run id or run directory")
    score.add_argument("--judge", action="store_true")
    score.add_argument("--judge-model")
    view = sub.add_parser("view", help="Serve the read-only local result browser")
    common(view, child=True)
    view.add_argument("--port", type=int, default=8765)
    demo = sub.add_parser(
        "demo",
        help="Create citation-upload scripted records, without any model/API calls",
    )
    common(demo, child=True)
    copy = sub.add_parser("copy-case", help="Copy a case to your own editable library")
    common(copy, child=True)
    copy.add_argument("case")
    copy.add_argument("--output", required=True, type=Path)
    sample = sub.add_parser(
        "new-sample",
        help="Add a sample to an explicitly selected editable case library",
    )
    common(sample, child=True)
    sample.add_argument("case")
    sample.add_argument("id")
    sample.add_argument("--from-sample")
    mcp = sub.add_parser("mcp", help=argparse.SUPPRESS)
    mcp.add_argument("--run-dir", required=True, type=Path)
    return root


def judge_config(args):
    settings = load_config(args.config).get("judge", {})
    if getattr(args, "judge_model", None):
        settings["model"] = args.judge_model
    if not settings.get("model"):
        raise ValueError(
            "Configure [judge].model or pass --judge-model; the judge has no implicit default model"
        )
    config = JudgeConfig(**settings)
    if not judge_api_key(config, args.env_file):
        raise ValueError(
            f"Set {config.api_key_env} or pass --env-file; no API request was made"
        )
    return config


def run_path(root, value):
    path = Path(value)
    if path.is_dir():
        return path.resolve()
    path = root / value
    if not (path / "run.json").is_file():
        raise ValueError(f"Run not found: {value}")
    return path.resolve()


def dispatch(args):
    if args.command == "mcp":
        from .mcp_server import main as serve_mcp

        return serve_mcp(args.run_dir)
    if args.command == "sources":
        from .source_registry import SOURCE_INDEX, check_updates, load_registry

        path = args.sources or SOURCE_INDEX
        if args.source_command == "list":
            for provider in load_registry(path)["providers"]:
                print(
                    f"{provider['id']:16} {provider['name']}  [{provider['source_count']} reviewed entries; {provider['observed_at']}] {provider['index_url']}"
                )
            return 0
        output = args.output or Path(".cache/source-checks") / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
            + ".json"
        )
        if output.exists():
            raise ValueError(
                "Review output already exists; choose a new path to preserve earlier checks"
            )
        result = check_updates(
            path, args.provider, content=args.content, timeout=args.timeout
        )
        write_json(output, result)
        for provider in result["providers"]:
            print(
                f"{provider['id']}: {provider['status']}; new={len(provider['new'])}, changed={len(provider['changed'])}, not listed={len(provider['not_listed'])}, untracked={len(provider['untracked'])}, errors={len(provider['errors'])}"
            )
        print(f"Review report: {output.resolve()}. No benchmark inputs were changed.")
        return 1 if result["status"] == "partial" else 0
    if args.command == "doctor":
        from .codex import capabilities, resolve_codex, DISABLED_FEATURES

        info = capabilities(resolve_codex(args.codex))
        print(
            json.dumps(
                {key: value for key, value in info.items() if key != "features"}
                | {
                    "disabled_features": sorted(
                        DISABLED_FEATURES.intersection(info["features"])
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        settings = load_config(args.config).get("judge", {})
        if settings:
            config = JudgeConfig(**settings)
            print(
                json.dumps(
                    {
                        "judge": asdict(config),
                        "credential_present": bool(
                            judge_api_key(config, args.env_file)
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                "Judge not configured. Agent execution and action scoring remain available."
            )
        return 0
    if args.command == "score":
        from .grading import judge, save_scores

        path = run_path(args.runs, args.run)
        if args.judge:
            config = judge_config(args)
            result = judge(path, config, api_key=judge_api_key(config, args.env_file))
        else:
            result = save_scores(path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["answer"]["status"] == "error" else 0
    cases = catalog(args.cases)
    if hasattr(args, "case") and args.case not in cases:
        raise ValueError(
            f"Unknown case {args.case!r}; use mrbench list to inspect the selected library"
        )
    if args.command == "coverage":
        from .coverage import SOURCE_INDEX, source_coverage

        print(
            json.dumps(
                source_coverage(cases, args.sources or SOURCE_INDEX),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "list":
        for case in cases.values():
            print(
                f"{case.id:24} {case.spec['title']}  [{len(case.samples)} sample(s), default {case.spec['default_sample']}]"
            )
    elif args.command == "validate":
        if args.cases is None or args.sources is not None:
            from .coverage import SOURCE_INDEX, validate_coverage

            validate_coverage(cases, args.sources or SOURCE_INDEX)
        print(
            f"Valid: {len(cases)} case(s), {sum(len(c.samples) for c in cases.values())} sample(s). No model/API calls."
        )
    elif args.command == "show":
        case = cases[args.case]
        sid = args.sample or case.spec["default_sample"]
        print(
            json.dumps(
                {
                    "case": case.spec,
                    "samples": list(case.samples),
                    "sample": case.samples[sid],
                    "rubric": case.environment(
                        sid, case.spec["default_condition"]
                    ).judge_context(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "run":
        from .codex import capabilities, resolve_codex
        from .grading import judge
        from .runs import run

        case = cases[args.case]
        sample_ids = (
            list(case.samples)
            if args.sample == "all"
            else [args.sample or case.spec["default_sample"]]
        )
        condition_ids = (
            [c["id"] for c in case.spec["conditions"]]
            if args.condition == "all"
            else [args.condition or case.spec["default_condition"]]
        )
        for sid in sample_ids:
            for cid in condition_ids:
                case.environment(sid, cid)
        config = judge_config(args) if args.judge else None
        info = capabilities(resolve_codex(args.codex))
        print(
            f"Episodes: {len(sample_ids)} sample(s) × {len(condition_ids)} condition(s) × {args.repeat} trial(s)",
            flush=True,
        )
        for sid in sample_ids:
            for cid in condition_ids:
                for trial in range(1, args.repeat + 1):
                    path = run(
                        case,
                        sid,
                        cid,
                        args.runs,
                        info,
                        args.model,
                        args.timeout,
                        args.max_calls,
                        args.effort,
                        trial,
                    )
                    if read_json(path / "run.json")["status"] != "completed":
                        print(
                            f"Stopped on incomplete/invalid run: {path}",
                            file=sys.stderr,
                        )
                        return 1
                    if config:
                        result = judge(
                            path, config, api_key=judge_api_key(config, args.env_file)
                        )
                        if result["answer"]["status"] == "error":
                            print(f"Stopped on judge error: {path}", file=sys.stderr)
                            return 1
    elif args.command == "view":
        from .viewer import serve

        serve(cases, args.runs, args.port, sources=args.sources)
    elif args.command == "demo":
        from .demo import create_demo

        if "citation-upload" not in cases:
            raise ValueError(
                "Scripted demos require the citation-upload case in the selected library"
            )
        for path in create_demo(cases["citation-upload"], args.runs):
            print(path)
    elif args.command == "copy-case":
        destination = args.output / args.case
        if destination.exists():
            raise ValueError(
                "Destination already exists; choose another output directory"
            )
        shutil.copytree(cases[args.case].path, destination)
        print(destination.resolve())
    elif args.command == "new-sample":
        if args.cases is None:
            raise ValueError(
                "Pass --cases with your editable library; packaged cases are left intact"
            )
        sid = identifier(args.id)
        case = cases[args.case]
        path = case.path / "samples" / f"{sid}.json"
        if path.exists():
            raise ValueError("Sample already exists")
        sample = dict(case.samples[args.from_sample or case.spec["default_sample"]])
        sample.update({"id": sid, "version": "1.0.0", "title": sid})
        # Keep the cloned sample only if the resulting library validates.
        case.environment(
            args.from_sample or case.spec["default_sample"],
            case.spec["default_condition"],
        )
        write_json(path, sample)
        try:
            load_case(case.path)
        except (OSError, ValueError, KeyError, TypeError):
            path.unlink()
            raise
        print(
            f"Created {path}. Edit task/data, then run validate. Default: {case.spec['default_sample']}"
        )
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        code = dispatch(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"mrbench: {exc}", file=sys.stderr)
        code = 2
    except KeyboardInterrupt:
        code = 130
    if code:
        raise SystemExit(code)
