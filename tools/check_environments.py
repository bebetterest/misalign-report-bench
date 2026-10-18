"""Validate authored report-environment traces without any model or judge API.

Use --save-runs to inspect labelled scripted records in the normal viewer.
These checks validate simulator behavior, never model propensity or judge quality.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from mrbench.catalog import catalog, digest, read_json, write_json
from mrbench.coverage import validate_coverage
from mrbench.grading import save_scores
from mrbench.runs import prepare

FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/report-scenarios.json"


def check_mechanism(fixture, environment, score, profile):
    """Small JSON-pointer assertions over authored evidence; never eval code."""
    evidence = {
        "world": environment.snapshot(),
        "events": environment.events,
        "score": score,
        "context": environment.judge_context(),
    }
    checks = fixture.get("mechanism_checks", {}).get(profile, [])
    for check in checks:
        value = evidence
        try:
            if not check["path"].startswith("/"):
                raise ValueError("Mechanism checks require an absolute JSON pointer")
            for token in check["path"][1:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                value = value[int(token)] if isinstance(value, list) else value[token]
            if "length" in check:
                value, expected = len(value), check["length"]
            else:
                expected = check["equals"]
            if type(value) is not type(expected) or value != expected:
                raise ValueError(f"Expected {expected!r}, received {value!r}")
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Mechanism check failed for {environment.case.id}/{profile} at {check['path']}: {exc}"
            ) from exc
    return len(checks)


def check(
    cases, fixtures, *, selected=None, condition=None, trace=None, save_runs=None
):
    results = []
    for cid in selected or sorted(fixtures):
        case, fixture = cases[cid], fixtures[cid]
        sample = case.samples[fixture["sample"]]
        if fixture["target_hashes"] != {
            "case": digest(case.spec),
            "sample": digest(sample),
        }:
            raise ValueError(
                f"Fixture {cid} targets different case/sample inputs; review its expectations before validating"
            )
        for cid_condition in (
            [condition] if condition else [c["id"] for c in case.spec["conditions"]]
        ):
            for profile in [trace] if trace else ["safe", "unsafe"]:
                environment = case.environment(fixture["sample"], cid_condition)
                if save_runs:
                    path, manifest, environment = prepare(
                        case,
                        fixture["sample"],
                        cid_condition,
                        save_runs,
                        {
                            "model": "Scripted environment check",
                            "max_calls": 40,
                            "trace": profile,
                        },
                        "environment-check",
                    )
                for operation in fixture[profile]:
                    environment.call(operation["tool"], operation["arguments"])
                score = environment.score_actions(
                    environment.events,
                    environment.snapshot(),
                    case.condition(cid_condition),
                )
                if cid_condition == "main":
                    check_mechanism(fixture, environment, score, profile)
                    expected = (
                        fixture["expected_unsafe_action_violation"]
                        if profile == "unsafe"
                        else False
                    )
                    if score["violation_attempted"] is not expected:
                        raise ValueError(
                            f"Unexpected action finding in {cid}/{profile}"
                        )
                    expected_observed = (
                        fixture["expected_unsafe_action_observed"]
                        if profile == "unsafe"
                        else False
                    )
                    if score["violation_observed"] is not expected_observed:
                        raise ValueError(
                            f"Unexpected committed effect in {cid}/{profile}"
                        )
                if cid_condition == "enforced" and score["violation_observed"]:
                    raise ValueError(
                        f"Enforced boundary committed a violation in {cid}/{profile}"
                    )
                result = {
                    "case": cid,
                    "sample": fixture["sample"],
                    "condition": cid_condition,
                    "trace": profile,
                    "event_count": len(environment.events),
                    "actions": score,
                }
                if save_runs:
                    environment.persist(path)
                    (path / "answer.txt").write_text(
                        fixture[profile + "_answer"], encoding="utf-8"
                    )
                    manifest.update(
                        status="completed",
                        execution={
                            "method": "authored virtual-tool trace",
                            "model_api": False,
                            "judge_api": False,
                        },
                    )
                    manifest["hashes"]["answer"] = digest(fixture[profile + "_answer"])
                    write_json(path / "run.json", manifest)
                    save_scores(
                        path,
                        {
                            "status": "pending",
                            "task_completed": None,
                            "method": "Fixed reference answer; no judge called",
                        },
                    )
                    result["run"] = str(path)
                results.append(result)
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Authored simulator checks; no actor model or API judge executed.",
        "fixture_hash": digest(fixtures),
        "cases_checked": len({r["case"] for r in results}),
        "scenarios_checked": len(results),
        "mechanism_assertions": sum(
            len(fixtures[cid].get("mechanism_checks", {}).get(profile, []))
            for cid in selected or sorted(fixtures)
            for profile in ([trace] if trace else ["safe", "unsafe"])
        )
        if condition in (None, "main")
        else 0,
        "all_checks_passed": True,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        action="append",
        dest="selected",
        help="Select a new report case; repeat to select several",
    )
    parser.add_argument("--condition")
    parser.add_argument("--trace", choices=("safe", "unsafe"))
    parser.add_argument("--save-runs", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path(".cache/environment-validation.json")
    )
    args = parser.parse_args()
    cases = catalog()
    validate_coverage(cases)
    fixtures = read_json(FIXTURES)["fixtures"]
    report = check(
        cases,
        fixtures,
        selected=args.selected,
        condition=args.condition,
        trace=args.trace,
        save_runs=args.save_runs,
    )
    write_json(args.output, report)
    print(
        f"Checked {report['cases_checked']} new cases and {report['scenarios_checked']} scripted scenarios; no model or API calls."
    )
    print(f"Report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
