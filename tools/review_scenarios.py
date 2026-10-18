"""Export exact task/tool instructions and available lower-trust source material.

This is a review aid, not an automated fidelity grade. Report metadata, answer
rubrics, expected facts, private service state and reference traces are excluded.
Source material is available through tools, not preloaded into the actor prompt.
"""

import argparse
from copy import deepcopy
from pathlib import Path

from mrbench.catalog import catalog, write_json
from mrbench.environments.simulation import Simulation


def actor_surface(case, sample_id, condition_id):
    environment = case.environment(sample_id, condition_id)
    sample, condition = environment.sample, environment.condition
    # Read the initialized world so the review matches actual condition data.
    # Only virtual files readable under the task policy are included. A local
    # .credentials file is a fictional task input, never a host credential.
    files = environment.snapshot().get("files", {})
    sources = {
        "readable_files": {
            path: text
            for path, text in files.items()
            if (
                environment.permitted(environment.file_scope(path))
                if isinstance(environment, Simulation)
                else path.startswith("/workspace/")
            )
        }
    }
    for key in ("session_material", "messages"):
        if key in sample:
            sources[key] = deepcopy(condition.get(key, sample[key]))
    return {
        "case": case.id,
        "sample": sample_id,
        "condition": condition_id,
        "user_task": environment.prompt,
        "trusted_instructions": environment.instructions,
        "tools": deepcopy(environment.tools),
        "available_lower_trust_material": sources,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", dest="selected")
    parser.add_argument("--cases", type=Path, help="An alternative case library")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = catalog(args.cases)
    selected = args.selected or sorted(cases)
    unknown = set(selected) - cases.keys()
    if unknown:
        parser.error("Unknown cases: " + ", ".join(sorted(unknown)))
    if args.output.exists():
        parser.error("Output already exists; choose a new review file")
    surfaces = [actor_surface(cases[cid], sid, condition["id"]) for cid in selected for sid in cases[cid].samples for condition in cases[cid].spec["conditions"]]
    write_json(args.output, {"scope": __doc__.strip(), "surfaces": surfaces})
    print(f"Exported {len(surfaces)} sample/condition surfaces for manual review; no models or APIs called.")


if __name__ == "__main__":
    main()
