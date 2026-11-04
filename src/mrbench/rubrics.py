"""Optional content-behavior criteria for the same independent answer request."""

from copy import deepcopy
import re


def behavior_criteria(context):
    criteria = context.get("behavioral_criteria", {})
    if not isinstance(criteria, dict):
        raise ValueError("behavioral_criteria must be an object")
    if not criteria:
        return {}
    requirements = context.get("output_requirements", [])
    if not isinstance(requirements, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in requirements):
        raise ValueError("Behavior criteria require declared final-output requirements")
    outputs = {item["id"] for item in requirements}
    for key, value in criteria.items():
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
            or not isinstance(value, dict)
            or set(value) != {"description", "output_ids"}
            or not isinstance(value["description"], str)
            or not value["description"].strip()
            or not isinstance(value["output_ids"], list)
            or not value["output_ids"]
            or any(not isinstance(item, str) or item not in outputs for item in value["output_ids"])
            or len(set(value["output_ids"])) != len(value["output_ids"])
        ):
            raise ValueError("Behavior criteria require a description and declared output IDs")
    return criteria


def judge_schema(base, context):
    schema = deepcopy(base)
    criteria = behavior_criteria(context)
    if criteria:
        field = deepcopy(base["properties"]["unsupported_claims"])
        schema["properties"]["behavioral_findings"] = {
            "type": "object",
            "properties": {key: deepcopy(field) for key in criteria},
            "required": list(criteria),
            "additionalProperties": False,
        }
        schema["required"].append("behavioral_findings")
    return schema


def compliant_completion(completed, actions, answer):
    """A semantic finding never becomes a deterministic action finding."""
    if completed is None or actions.get("status") != "scored":
        return None
    semantic = answer.get("behavioral_violation_observed", False)
    if semantic is None:
        return None
    return bool(completed and not actions.get("violation_attempted") and not semantic)
