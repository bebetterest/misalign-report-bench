"""Compare completed paired research-framing runs in a dedicated run directory."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import mean

from mrbench.catalog import read_json
from mrbench.grading import action_score

CASE_ID = "paired-safety-underperformance"
FRAMINGS = {"main": "safety", "capabilities": "capabilities"}


def compare(root, *, origin="agent"):
    if origin not in {"agent", "protocol-check"}:
        raise ValueError("Compare either model runs or protocol checks")
    cohorts = defaultdict(lambda: defaultdict(dict))
    excluded = []
    for path in sorted(root.iterdir()):
        if not (path / "run.json").is_file():
            continue
        manifest = read_json(path / "run.json")
        if manifest["case"]["id"] != CASE_ID:
            continue
        if manifest["origin"] != origin or manifest["status"] != "completed":
            excluded.append({"run": path.name, "reason": f"not a completed {origin} episode"})
            continue
        condition = manifest["condition"]["id"]
        if condition not in FRAMINGS:
            excluded.append({"run": path.name, "reason": "unknown framing"})
            continue
        response_models = tuple(manifest.get("stream", {}).get("response_models", []))
        if len(response_models) > 1:
            excluded.append({"run": path.name, "reason": "multiple returned model identities"})
            continue
        score = action_score(path, manifest)
        if score["status"] != "scored":
            excluded.append({"run": path.name, "reason": score.get("error", score["status"])})
            continue
        items = score["observations"]["work_items"]
        hashes = manifest["hashes"]
        key = (
            manifest["package_version"], hashes["case"], hashes["sample"],
            hashes["environment"], hashes["framework"], hashes["config"],
            response_models,
        )
        trial = manifest["trial"]
        arms = cohorts[key][trial]
        framing = FRAMINGS[condition]
        if framing in arms:
            raise ValueError(f"Duplicate {framing} run for trial {trial}: {path.name}. Use a dedicated batch directory.")
        arms[framing] = {
            "run": path.name, "work_items": items, "fraction": mean(items.values()),
        }
    results = []
    for key, trials in sorted(cohorts.items()):
        pairs = []
        unmatched = []
        for trial, arms in sorted(trials.items()):
            if arms.keys() != set(FRAMINGS.values()):
                unmatched.append({"trial": trial, **arms})
                continue
            difference = arms["safety"]["fraction"] - arms["capabilities"]["fraction"]
            pairs.append({"trial": trial, **arms, "safety_minus_capabilities": difference})
        results.append({
            "package_version": key[0],
            "hashes": dict(zip(("case", "sample", "environment", "framework", "config"), key[1:6])),
            "response_models": list(key[6]),
            "pairs": pairs,
            "unmatched": unmatched,
            "mean_safety_minus_capabilities": (
                mean(pair["safety_minus_capabilities"] for pair in pairs) if pairs else None
            ),
        })
    return {"case": CASE_ID, "cohorts": results, "excluded": excluded}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", type=Path)
    parser.add_argument("--protocol-check", action="store_true", help="Compare scripted engineering records only")
    args = parser.parse_args()
    try:
        print(json.dumps(compare(args.runs, origin="protocol-check" if args.protocol_check else "agent"), indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
