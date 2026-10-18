"""Check explicitly labelled report answers with the independent API judge.

No actor runs. Each selected reference gets one request, without retries.
Use --prepare-only to inspect all inputs without using the API. These authored
expectations are development checks, not independent human calibration.
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import uuid

if __package__:
    from .check_judge import check_suite
else:
    from check_judge import check_suite
from mrbench.catalog import catalog, digest, read_json, write_json
from mrbench.config import JudgeConfig, judge_api_key, load_config


FIXTURES = Path(__file__).resolve().parents[1] / "tests/fixtures/report-scenarios.json"


def reference_suite(case, fixture):
    sample = case.samples[fixture["sample"]]
    if fixture["target_hashes"] != {
        "case": digest(case.spec),
        "sample": digest(sample),
    }:
        raise ValueError(
            "Review and rebind changed case/sample reference expectations first"
        )
    expectations = fixture.get("answer_expectations")
    if not expectations:
        raise ValueError(
            f"No reviewed answer expectations for {case.id}; no API call made"
        )
    return {
        "schema_version": 1,
        "id": case.id + "-answer-check",
        "version": fixture.get("answer_reference_version", "2.0.0"),
        "label_provenance": fixture["label_provenance"],
        "target": {
            "case": case.id,
            "sample": sample["id"],
            "case_version": case.spec["version"],
            "sample_version": sample["version"],
            "case_hash": digest(case.spec),
            "sample_hash": digest(sample),
        },
        "fixtures": [
            {
                "id": profile,
                "condition": case.spec["default_condition"],
                "answer": fixture[profile + "_answer"],
                "output_trace": fixture[profile]
                if sample.get("answer_outputs")
                else [],
                "expected": expected,
            }
            for profile, expected in expectations.items()
        ]
        + fixture.get("answer_checks", []),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--case", action="append", dest="selected")
    selection.add_argument(
        "--all",
        action="store_true",
        help="Check every report fixture; lake references use check_judge.py",
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    cases, fixtures = catalog(), read_json(FIXTURES)["fixtures"]
    selected = sorted(fixtures) if args.all else list(dict.fromkeys(args.selected))
    # Validate every selected reference before preparing or sending any request.
    suites = {cid: reference_suite(cases[cid], fixtures[cid]) for cid in selected}
    config = JudgeConfig(**load_config(args.config).get("judge", {}))
    key = judge_api_key(config, args.env_file)
    if not args.prepare_only and not key:
        parser.error("Judge credentials are required; no API call was made")
    output = (
        args.output
        or Path(".cache/report-judge-checks")
        / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        )
    ).resolve()
    output.mkdir(parents=True, exist_ok=False)
    summary = {
        "schema_version": 1,
        "scope": "Authored fixed answers; no actor or independent human calibration.",
        "planned_cases": selected,
        "planned_answers": sum(len(s["fixtures"]) for s in suites.values()),
        "prepared_only": args.prepare_only,
        "results": [],
        "all_reference_expectations_met": False,
    }
    for cid, suite in suites.items():
        path = output / (cid + ".json")
        write_json(path, suite)
        result = check_suite(
            path, output / cid, config, api_key=key, prepare_only=args.prepare_only
        )
        summary["results"].append(result)
        write_json(output / "summary.json", summary)
        if result["status"] == "stopped_on_api_error":
            break
    summary["all_reference_expectations_met"] = (
        not args.prepare_only
        and len(summary["results"]) == len(suites)
        and all(
            result["all_reference_expectations_met"] for result in summary["results"]
        )
    )
    summary["scored"] = sum(r["scored"] for r in summary["results"])
    summary["agreed"] = sum(r["agreed"] for r in summary["results"])
    write_json(output / "summary.json", summary)
    print(f"Saved: {output / 'summary.json'}", flush=True)
    print(
        f"Reference agreement: {summary['agreed']}/{summary['planned_answers']}; scored={summary['scored']}"
    )
    if not args.prepare_only and not summary["all_reference_expectations_met"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
