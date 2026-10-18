"""Environment boundary. Tool calls never expose the grader or host filesystem."""

from abc import ABC, abstractmethod
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from importlib import import_module
import inspect
import json

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable

from .catalog import digest, write_json


def _deny_schema_retrieval(uri):
    raise NoSuchResource(ref=uri)


def implementation_source(environment):
    """Bind shared environment logic too; preserve the legacy single-file hash."""
    primary = Path(inspect.getfile(type(environment))).read_text(encoding="utf-8")
    modules = getattr(environment, "evidence_modules", ())
    if not modules:
        return primary
    return {
        "primary": primary,
        **{
            name: Path(inspect.getfile(import_module(name))).read_text(encoding="utf-8")
            for name in modules
        },
    }


class Environment(ABC):
    def __init__(self, case, sample: dict, condition: dict):
        self.case = case
        self.sample = deepcopy(sample)
        self.condition = deepcopy(condition)
        self.events = []
        self.max_calls = 40

    @property
    @abstractmethod
    def tools(self) -> list[dict]:
        """MCP-compatible name, description, inputSchema; no host execution tools."""

    @property
    def prompt(self) -> str:
        return self.sample["task"] + self.condition.get("task_suffix", "")

    @property
    def instructions(self) -> str:
        """Trusted tool/authorization policy, kept separate from source content."""
        return ""

    def task_effects_complete(self):
        """Optional objective deliverable predicate, independent of answer judging."""
        return None

    def final_outputs(self, state=None):
        """Only declared final task texts; no trajectory, permissions or hidden state."""
        return []

    @abstractmethod
    def handle(self, name: str, arguments: dict) -> tuple[dict, list[dict]]:
        """Return a tool result and objectively observable effects."""

    @abstractmethod
    def snapshot(self) -> dict:
        """Serializable world state, independent of the model transcript."""

    @abstractmethod
    def judge_context(self) -> dict:
        """Task, expected facts, source support and constraints. No action events."""

    @staticmethod
    @abstractmethod
    def score_actions(events: list[dict], state: dict, condition: dict) -> dict:
        """Case-specific deterministic scoring, never a model-judged trajectory."""

    def call(self, name: str, arguments: dict) -> dict:
        if len(self.events) >= self.max_calls:
            raise RuntimeError("Environment tool-call budget exhausted")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        try:
            definition = next((t for t in self.tools if t["name"] == name), None)
            if definition is None:
                raise ValueError(f"Unknown tool: {name}")
            schema = definition["inputSchema"]
            try:
                invalid = next(
                    Draft202012Validator(
                        schema, registry=Registry(retrieve=_deny_schema_retrieval)
                    ).iter_errors(arguments),
                    None,
                )
            except Unresolvable as exc:
                raise ValueError(
                    "Tool schemas cannot retrieve external references"
                ) from exc
            if invalid is not None:
                raise ValueError("Invalid tool arguments: " + invalid.message)
            result, effects = self.handle(name, deepcopy(arguments))
        except (ValueError, KeyError, TypeError) as exc:
            result, effects = {"error": str(exc)}, []
        event = {
            "seq": len(self.events) + 1,
            "time": datetime.now(timezone.utc).isoformat(),
            "tool": name,
            "arguments": deepcopy(arguments),
            "result": result,
            "effects": effects,
            "previous_hash": self.events[-1]["hash"] if self.events else None,
        }
        event["hash"] = digest(event)
        self.events.append(event)
        return result

    def persist(self, run_dir: Path):
        # stdout belongs exclusively to the MCP protocol.
        event_file = run_dir / "events.jsonl"
        written = getattr(self, "_persisted", 0)
        with event_file.open("a", encoding="utf-8") as stream:
            for event in self.events[written:]:
                stream.write(
                    json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
                )
        self._persisted = len(self.events)
        state = self.snapshot()
        write_json(
            run_dir / "state.json",
            {
                "world": state,
                "event_count": len(self.events),
                "last_event_hash": self.events[-1]["hash"] if self.events else None,
                "world_hash": digest(state),
            },
        )
