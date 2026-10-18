"""Small harness contract and shared subprocess supervision."""

from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Protocol
import inspect
import json
import os
import re
import signal
import subprocess

from ..catalog import digest


def configuration_artifact(name):
    return name in {"command.json", "model-catalog.json", "grok-config.json"} or bool(
        isinstance(name, str) and re.fullmatch(r"harness-[a-z0-9-]{1,64}\.json", name)
    )


@dataclass(frozen=True)
class HarnessConfig:
    model: str | None = None
    executable: str | None = None
    options: dict = field(default_factory=dict)
    # Programmatic protocol checks can route the native CLI to localhost.
    provider_config: dict = field(default_factory=dict)
    use_auth: bool = True


@dataclass(frozen=True)
class HarnessInfo:
    id: str
    version: str
    profile: str
    executable: str
    settings: dict
    artifacts: dict = field(default_factory=dict)
    runtime: dict = field(default_factory=dict, repr=False)

    def metadata(self, adapter):
        sources = {
            name: Path(inspect.getfile(import_module(name))).read_text(encoding="utf-8")
            for name in adapter.evidence_modules
        }
        return {
            "id": self.id,
            "version": self.version,
            "profile": self.profile,
            "adapter_hash": digest(sources),
        }


@dataclass(frozen=True)
class Episode:
    """Only actor-visible inputs and runtime locations; no rubric or hidden state."""

    run_dir: Path
    workspace: Path
    prompt: str
    instructions: str
    model: str
    timeout: int
    max_calls: int
    effort: str
    tool_names: tuple[str, ...]
    info: HarnessInfo


@dataclass(frozen=True)
class HarnessResult:
    execution: dict
    stream: dict
    answer: str | None = None


class HarnessAdapter(Protocol):
    id: str
    evidence_modules: tuple[str, ...]

    def preflight(self, config: HarnessConfig) -> HarnessInfo: ...

    def run(self, episode: Episode) -> HarnessResult: ...


def toml_literal(value):
    if isinstance(value, dict):
        return "{" + ", ".join(
            f"{json.dumps(key)} = {toml_literal(item)}" for key, item in value.items()
        ) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(toml_literal(item) for item in value) + "]"
    if isinstance(value, (str, bool, int, float)):
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    raise ValueError("Unsupported TOML configuration value")


def execute_process(args, prompt, workspace, prefix, timeout, environment):
    """Supervise the whole process group, including native MCP children."""
    with (
        prefix.with_suffix(".jsonl").open("w", encoding="utf-8") as out,
        prefix.with_suffix(".stderr.log").open("w", encoding="utf-8") as err,
    ):
        try:
            process = subprocess.Popen(
                args, cwd=workspace, stdin=subprocess.PIPE, stdout=out, stderr=err,
                text=True, start_new_session=True, env=environment,
            )
        except OSError as exc:
            err.write(str(exc))
            return {"exit_code": -1, "timed_out": False, "error": "Process could not start"}
        try:
            process.communicate(prompt, timeout=timeout)
            return {"exit_code": process.returncode, "timed_out": False}
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            return {
                "exit_code": process.returncode,
                "timed_out": isinstance(exc, subprocess.TimeoutExpired),
                "interrupted": isinstance(exc, KeyboardInterrupt),
            }
