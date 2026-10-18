"""A case describes a mechanism; a sample supplies task data; conditions vary the environment."""

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from importlib import import_module
from pathlib import Path
import json
import re

BUILTIN_CASES = Path(__file__).parent / "cases"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")


@lru_cache(maxsize=256)
def validate_tool_schema(encoded):
    from jsonschema import Draft202012Validator, SchemaError

    try:
        Draft202012Validator.check_schema(json.loads(encoded))
    except SchemaError as exc:
        raise ValueError("Invalid JSON tool input schema") from exc


def identifier(value: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid identifier: {value!r}")
    return value


def digest(value) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def comparison_config(config):
    """Condition policy is already bound by case/sample/condition snapshots."""
    return {key: value for key, value in config.items() if key != "task_tool_policy"}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


@dataclass(frozen=True)
class Case:
    path: Path
    spec: dict
    samples: dict[str, dict]

    @property
    def id(self):
        return self.spec["id"]

    def condition(self, name: str):
        try:
            return next(c for c in self.spec["conditions"] if c["id"] == name)
        except StopIteration:
            raise ValueError(f"Unknown condition {name!r} in {self.id}") from None

    def environment(self, sample_id: str, condition_id: str):
        from .environment import Environment

        if sample_id not in self.samples:
            raise ValueError(f"Unknown sample {sample_id!r} in {self.id}")
        module, name = self.spec["environment"].split(":", 1)
        try:
            implementation = getattr(import_module(module), name)
        except (ImportError, AttributeError) as exc:
            raise ValueError(
                f"Cannot load environment {self.spec['environment']}: {exc}"
            ) from exc
        if not issubclass(implementation, Environment):
            raise ValueError("Case environment must implement Environment")
        return implementation(
            self, self.samples[sample_id], self.condition(condition_id)
        )


def load_case(path: Path) -> Case:
    spec = read_json(path / "case.json")
    if not isinstance(spec, dict):
        raise ValueError("Case definition must be a JSON object")
    if spec.get("schema_version") != 1:
        raise ValueError(f"Unsupported case schema in {path}")
    identifier(spec["id"])
    for key in (
        "title",
        "summary",
        "version",
        "category",
        "environment",
        "source",
        "abstraction",
        "conditions",
        "default_sample",
        "default_condition",
    ):
        if not spec.get(key):
            raise ValueError(f"Missing case field: {key}")
    for key in (
        "title",
        "summary",
        "version",
        "category",
        "environment",
        "default_sample",
        "default_condition",
    ):
        if not isinstance(spec[key], str) or not spec[key].strip():
            raise ValueError(f"Case field must be a nonempty string: {key}")
    digest(spec)
    if (
        not isinstance(spec["source"], dict)
        or not isinstance(spec["abstraction"], dict)
        or not isinstance(spec["conditions"], list)
        or any(not isinstance(item, dict) for item in spec["conditions"])
    ):
        raise ValueError("Invalid source, abstraction or conditions structure")
    for key in ("title", "url", "updated", "scope"):
        if not isinstance(spec["source"].get(key), str) or not spec["source"][key]:
            raise ValueError(f"Missing source field: {key}")
    for key in ("preserved", "changed", "not_reproduced"):
        if not isinstance(spec["abstraction"].get(key), list) or any(
            not isinstance(item, str) for item in spec["abstraction"][key]
        ):
            raise ValueError(f"Invalid abstraction list: {key}")
    review = spec.get("scenario_review")
    if review is not None and (
        not isinstance(review, dict)
        or any(not isinstance(review.get(key), str) or not review[key].strip() for key in ("reviewed_at", "kind", "fidelity", "source_task", "tested_mechanism"))
        or not isinstance(review.get("limits"), list)
        or not review["limits"]
        or any(not isinstance(item, str) or not item.strip() for item in review["limits"])
    ):
        raise ValueError("Scenario review requires a source task, study boundary and interpretation limits")
    for condition in spec["conditions"]:
        if not isinstance(condition.get("title"), str) or not condition["title"]:
            raise ValueError("Each condition needs a title")
        if not isinstance(condition.get("task_suffix", ""), str):
            raise ValueError("Condition task_suffix must be text")
    conditions = [identifier(c["id"]) for c in spec["conditions"]]
    if (
        len(set(conditions)) != len(conditions)
        or spec["default_condition"] not in conditions
    ):
        raise ValueError("Conditions must be unique and include the default")
    samples = {}
    for sample_path in sorted((path / "samples").glob("*.json")):
        sample = read_json(sample_path)
        if not isinstance(sample, dict):
            raise ValueError("Sample definition must be a JSON object")
        sid = identifier(sample["id"])
        if (
            sid in samples
            or sample.get("schema_version") != 1
            or not isinstance(sample.get("version"), str)
            or not sample["version"].strip()
        ):
            raise ValueError(f"Invalid or duplicate sample: {sample_path}")
        for key in ("title", "task"):
            if not isinstance(sample.get(key), str) or not sample[key]:
                raise ValueError(f"Missing sample field: {key}")
        digest(sample)
        samples[sid] = sample
    if spec["default_sample"] not in samples:
        raise ValueError("Case requires an existing default sample")
    case = Case(path.resolve(), spec, samples)
    # Validate every sample/condition before any model is invoked.
    for sid in samples:
        for cid in conditions:
            environment = case.environment(sid, cid)
            context = environment.judge_context()
            if not isinstance(context, dict):
                raise ValueError("Judge context must be a JSON object")
            criteria = context.get("completion_criteria", {})
            known_fields = {
                "answer_correct",
                "source_attribution_correct",
                "limitation_disclosed",
                "unsupported_claims",
                "citation_complete",
            }
            if (
                not isinstance(context.get("rubric"), str)
                or not context["rubric"].strip()
                or context.get("task") != environment.prompt
                or not isinstance(criteria, dict)
                or not criteria
                or set(criteria) - known_fields
                or any(not isinstance(value, bool) for value in criteria.values())
            ):
                raise ValueError(
                    "Judge context requires the exact task, a text rubric and boolean completion_criteria using known fields"
                )
            not_applicable = context.get("not_applicable_fields", [])
            if (
                not isinstance(not_applicable, list)
                or any(
                    not isinstance(key, str) or key not in known_fields
                    for key in not_applicable
                )
                or set(not_applicable).intersection(criteria)
            ):
                raise ValueError(
                    "Inapplicable judge fields must be known fields outside completion_criteria"
                )
            tools = environment.tools
            names = [tool["name"] for tool in tools]
            if len(names) != len(set(names)) or any(
                not isinstance(name, str) or not name for name in names
            ):
                raise ValueError("Environment tools must have unique names")
            for tool in tools:
                schema = tool["inputSchema"]
                validate_tool_schema(
                    json.dumps(schema, sort_keys=True, allow_nan=False)
                )
                if (
                    schema.get("type") != "object"
                    or not isinstance(schema.get("properties"), dict)
                    or not isinstance(schema.get("required"), list)
                ):
                    raise ValueError(
                        "Tool inputSchema requires object properties and required fields"
                    )
                if set(schema["required"]) - set(schema["properties"]):
                    raise ValueError("Required tool arguments must be defined")
            digest(context)  # Also rejects non-JSON values and NaN before inference.
    return case


def catalog(extra: Path | None = None) -> dict[str, Case]:
    result = {}
    for root in [extra.resolve() if extra else BUILTIN_CASES]:
        if not root.is_dir():
            raise ValueError(f"Case directory does not exist: {root}")
        for path in sorted(root.iterdir()):
            if (path / "case.json").is_file():
                case = load_case(path)
                if case.id in result:
                    raise ValueError(f"Duplicate case id: {case.id}")
                result[case.id] = case
    return result
