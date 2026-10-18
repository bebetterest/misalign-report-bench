"""Check the production answer judge against fixed, versioned reference answers.

No actor is executed. Reference expectations are not sent to the API. These
checks measure agreement with authored expectations, not human calibration.
"""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import uuid

from mrbench.catalog import catalog, digest, read_json, write_json
from mrbench.config import JudgeConfig, judge_api_key, load_config
from mrbench.grading import JUDGE_FIELDS, judge
from mrbench.outputs import freeze_outputs
from mrbench.runs import prepare


DEFAULT_SUITE = (
    Path(__file__).resolve().parents[1]
    / "tests/fixtures/judge-quality-citation-upload.json"
)


def load_suite(path):
    suite = read_json(path)
    target = suite["target"]
    case = catalog()[target["case"]]
    sample = case.samples[target["sample"]]
    if (
        suite.get("schema_version") != 1
        or target["case_version"] != case.spec["version"]
        or target["sample_version"] != sample["version"]
        or target["case_hash"] != digest(case.spec)
        or target["sample_hash"] != digest(sample)
    ):
        raise ValueError(
            "Reference suite targets different case/sample inputs; review and version it before calling the API"
        )
    fixtures = suite["fixtures"]
    if not fixtures or len({f["id"] for f in fixtures}) != len(fixtures):
        raise ValueError("Reference suite requires unique, nonempty fixtures")
    for fixture in fixtures:
        case.condition(fixture["condition"])
        if not fixture["answer"].strip() or not fixture["expected"]:
            raise ValueError("Each fixture needs an answer and declared expectations")
        for key, value in fixture["expected"].items():
            if key not in (*JUDGE_FIELDS, "task_completed") or (
                value is not None and type(value) is not bool
            ):
                raise ValueError("Invalid reference expectation")
        trace = fixture.get("output_trace", [])
        if (
            not isinstance(trace, list)
            or len(trace) > 40
            or any(
                not isinstance(call, dict)
                or set(call) != {"tool", "arguments"}
                or not isinstance(call["tool"], str)
                or not isinstance(call["arguments"], dict)
                for call in trace
            )
        ):
            raise ValueError(
                "Reference output_trace must be a bounded virtual-tool trace"
            )
    return suite, case


def check_suite(
    suite_path,
    output,
    config,
    *,
    api_key=None,
    prepare_only=False,
    limit=None,
    transport=None,
):
    suite, case = load_suite(suite_path)
    fixtures = suite["fixtures"][:limit]
    if not prepare_only and not api_key:
        raise ValueError("Judge credentials are required; no API call was made")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "suite.json", suite)
    write_json(output / "judge-config.json", asdict(config))
    prepared = []
    for fixture in fixtures:
        path, manifest, environment = prepare(
            case,
            suite["target"]["sample"],
            fixture["condition"],
            output / "answers",
            {"model": "fixed-reference-answer", "max_calls": 40},
            origin="judge-check",
        )
        for call in fixture.get("output_trace", []):
            environment.call(call["tool"], call["arguments"])
        environment.persist(path)
        (path / "answer.txt").write_text(fixture["answer"], encoding="utf-8")
        manifest.update(
            status="completed",
            reference_id=fixture["id"],
            notice="Fixed answer for judge validation. No agent was executed; action metrics are not applicable.",
        )
        manifest["hashes"]["answer"] = digest(fixture["answer"])
        write_json(path / "run.json", manifest)
        freeze_outputs(path, manifest)
        # Expectations stay outside judge-context.json and the request payload.
        write_json(path / "reference.json", fixture)
        prepared.append((fixture, path))
    summary = {
        "schema_version": 1,
        "suite_id": suite["id"],
        "suite_version": suite["version"],
        "suite_hash": digest(suite),
        "judge_config": asdict(config),
        "label_provenance": suite["label_provenance"],
        "scope": "Fixed reference answers only; no actor or model-behavior experiment.",
        "suite_total": len(suite["fixtures"]),
        "planned": len(prepared),
        "judged": 0,
        "scored": 0,
        "agreed": 0,
        "unscored": 0,
        "unjudged": len(prepared),
        "results": [],
        "status": "prepared" if prepare_only else "running",
        "all_reference_expectations_met": False,
    }
    write_json(output / "summary.json", summary)
    if prepare_only:
        return summary
    for fixture, path in prepared:
        scores = judge(path, config, api_key=api_key, transport=transport)
        answer = scores["answer"]
        mismatches = {}
        if answer["status"] == "scored":
            for key, expected in fixture["expected"].items():
                actual = (
                    answer.get("task_completed")
                    if key == "task_completed"
                    else answer["evaluation"][key]["value"]
                )
                if actual is not expected:
                    mismatches[key] = {"expected": expected, "actual": actual}
        agreed = answer["status"] == "scored" and not mismatches
        result = {
            "id": fixture["id"],
            "run": str(path.relative_to(output)),
            "status": answer["status"],
            "agreed": agreed,
            "mismatches": mismatches,
            "config_hash": answer.get("config_hash"),
            "response_model": answer.get("response_model"),
            "system_fingerprint": answer.get("system_fingerprint"),
            "usage": answer.get("usage"),
        }
        summary["results"].append(result)
        summary["judged"] += 1
        summary["unjudged"] -= 1
        summary["scored"] += int(answer["status"] == "scored")
        summary["agreed"] += int(agreed)
        summary["unscored"] += int(answer["status"] != "scored")
        summary["status"] = (
            "stopped_on_api_error" if answer["status"] == "error" else "running"
        )
        write_json(output / "summary.json", summary)
        print(
            f"{fixture['id']}: {answer['status']}; reference agreement={agreed}",
            flush=True,
        )
        if answer["status"] == "error":
            break
    if summary["status"] != "stopped_on_api_error":
        summary["status"] = "complete"
    summary["all_reference_expectations_met"] = (
        summary["agreed"] == summary["planned"] and summary["unjudged"] == 0
    )
    write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Save all inputs without an API call",
    )
    parser.add_argument(
        "--limit", type=int, help="Explicitly check only the first N answers"
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    output = args.output or Path(".cache/judge-checks") / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )
    config = JudgeConfig(**load_config(args.config).get("judge", {}))
    summary = check_suite(
        args.suite,
        output,
        config,
        api_key=judge_api_key(config, args.env_file),
        prepare_only=args.prepare_only,
        limit=args.limit,
    )
    print(f"Saved: {output.resolve()}/summary.json", flush=True)
    print(
        f"Agreement: {summary['agreed']}/{summary['planned']}; unscored={summary['unscored']}, unjudged={summary['unjudged']}"
    )
    if not args.prepare_only and not summary["all_reference_expectations_met"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
