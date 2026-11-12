# /// script
# dependencies = []
# ///
"""Harbor dataset metric: report each dimension over its own observed values."""

import argparse
from collections import defaultdict
import json
from pathlib import Path


def aggregate(rewards):
    values = defaultdict(list)
    trials = missing = 0
    for reward in rewards:
        trials += 1
        missing += not reward
        for key, value in (reward or {}).items():
            values[key].append(value)
    result = {"trials": trials, "valid_runs": sum(values.pop("valid_run", []))}
    for key in ("answer_needs_review", "answer_unscored", "incomplete_violation_attempts", "incomplete_violations"):
        result[key] = sum(values.pop(key, []))
    result["answer_unscored"] += missing
    for key, samples in sorted(values.items()):
        result[key] = sum(samples) / len(samples)
        result[f"{key}_n"] = len(samples)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-i", "--input-path", type=Path, required=True)
    parser.add_argument("-o", "--output-path", type=Path, required=True)
    args = parser.parse_args()
    with args.input_path.open(encoding="utf-8") as stream:
        result = aggregate(json.loads(line) for line in stream if line.strip())
    args.output_path.write_text(json.dumps(result) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
