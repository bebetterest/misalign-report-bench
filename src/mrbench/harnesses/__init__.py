"""Explicit harness registry and read-only legacy record interpretation."""

from importlib import import_module
import re

from .base import Episode, HarnessAdapter, HarnessConfig, HarnessInfo, HarnessResult

REGISTRY = {
    "codex": "mrbench.harnesses.codex:CodexHarness",
    "grok": "mrbench.harnesses.grok:GrokHarness",
}


def get_harness(name="codex"):
    if name not in REGISTRY:
        raise ValueError(f"Unknown harness {name!r}; choose from {', '.join(REGISTRY)}")
    module, implementation = REGISTRY[name].split(":")
    return getattr(import_module(module), implementation)()


def is_agent_run(record):
    return record.get("origin") in ("agent", "codex")


def is_protocol_run(record):
    return record.get("origin") in ("protocol-check", "codex-smoke")


def harness_metadata(record):
    if isinstance(record.get("harness"), dict):
        return record["harness"]
    if record.get("origin") in ("codex", "codex-smoke"):
        config = record.get("config", {})
        return {
            "id": "codex", "version": config.get("codex_version", "unknown"),
            "profile": record.get("profile", config.get("profile", "legacy")),
        }
    return None


def native_log_names(record):
    name = (harness_metadata(record) or {}).get("id", "codex")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", name):
        raise ValueError("Invalid recorded harness identity")
    return name + ".jsonl", name + ".stderr.log"


__all__ = [
    "Episode", "HarnessAdapter", "HarnessConfig", "HarnessInfo", "HarnessResult",
    "REGISTRY", "get_harness", "is_agent_run", "is_protocol_run", "harness_metadata", "native_log_names",
]
