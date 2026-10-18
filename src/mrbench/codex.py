"""Real Codex CLI adapter. No agent loop or model API is reimplemented here."""

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile

from .catalog import digest
from .harnesses.base import execute_process

PROFILE_VERSION = "codex-mcp-closed-v4"
REQUIRED_FEATURES = {
    "code_mode",
    "code_mode_host",
    "shell_tool",
    "apps",
    "plugins",
    "hooks",
    "memories",
    "multi_agent",
    "skip_host_skill_discovery",
}
DISABLED_FEATURES = {
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "remote_plugin",
    "hooks",
    "memories",
    "multi_agent",
    "multi_agent_v2",
    "computer_use",
    "browser_use",
    "browser_use_external",
    "in_app_browser",
    "image_generation",
    "workspace_dependencies",
    "view_image",
    "skill_search",
    "sleep_tool",
    "chronicle",
    "goals",
}


def resolve_codex(value: str | None = None) -> str:
    found = shutil.which(value or "codex")
    desktop = Path(
        "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"
    )
    if not found and value is None and desktop.is_file():
        found = str(desktop)
    if not found:
        raise ValueError(
            "Codex CLI was not found. Install it or pass --codex /absolute/path/to/codex."
        )
    return str(Path(found).resolve())


def resolve_code_mode_host(executable: str) -> str:
    binary = Path(executable)
    candidates = [shutil.which("codex-code-mode-host"), binary.parent / "codex-code-mode-host"]
    if len(binary.parents) > 3:
        candidates.append(binary.parents[3] / "bin" / "codex-code-mode-host")
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise ValueError(
        "Codex Code Mode host was not found. Install the matching CLI companion; no model was started."
    )


def capabilities(executable: str) -> dict:
    def inspect(args):
        try:
            result = subprocess.run(
                [executable, *args], capture_output=True, text=True, timeout=15
            )
        except subprocess.TimeoutExpired:
            raise ValueError("Codex capability check timed out after 15 seconds. No model was started.") from None
        if result.returncode:
            raise ValueError(
                f"Codex preflight failed: {' '.join(args)}: {result.stderr.strip()}"
            )
        return result.stdout

    version = inspect(["--version"]).strip()
    help_text = inspect(["exec", "--help"])
    required_flags = [
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--json",
        "--strict-config",
    ]
    missing = [f for f in required_flags if f not in help_text]
    features = set(
        line.split()[0]
        for line in inspect(["features", "list"]).splitlines()
        if line.strip()
    )
    missing.extend(sorted(REQUIRED_FEATURES - features))
    if missing:
        raise ValueError(
            f"This Codex version cannot run the reference profile; missing: {', '.join(missing)}. No model was started."
        )
    return {
        "executable": executable,
        "version": version,
        "code_mode_host": resolve_code_mode_host(executable),
        "features": sorted(features),
        "profile": PROFILE_VERSION,
        "context_guard": "isolated temporary runtime",
    }


def toml(value):
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(f"{json.dumps(k)} = {toml(v)}" for k, v in value.items())
            + "}"
        )
    if isinstance(value, list):
        return "[" + ", ".join(toml(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def reference_catalog(info: dict, model: str) -> tuple[dict, dict]:
    """Use the installed CLI's offline metadata, with host tools removed.

    Code Mode models discover tools at runtime. Disabling shell alone does not
    remove apply_patch or model-specific experimental tools from that runtime.
    Keep the vendor model instructions and all other metadata unchanged.
    """
    try:
        result = subprocess.run(
            [info["executable"], "debug", "models", "--bundled"],
            capture_output=True, text=True, timeout=15,
        )
        catalog = json.loads(result.stdout) if result.returncode == 0 else {}
        matches = [m for m in catalog.get("models", []) if m.get("slug") == model]
        if len(matches) != 1:
            raise ValueError
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
        raise ValueError(
            "The installed CLI must supply bundled metadata for the requested model. "
            "Check `codex debug models --bundled`; no model was started."
        ) from None
    original = matches[0]
    overrides = {"apply_patch_tool_type": None, "experimental_supported_tools": []}
    effective = {"models": [{**original, **overrides}]}
    return effective, {
        "source": "installed CLI: debug models --bundled",
        "original_model_hash": digest(original),
        "effective_catalog_hash": digest(effective),
        "overrides": overrides,
    }


def command(
    info: dict,
    model: str,
    workspace: Path,
    output: Path,
    *,
    run_dir: Path,
    effort: str = "medium",
    task_instructions: str = "",
) -> list[str]:
    args = [
        info["executable"],
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "--json",
        "--color",
        "never",
        "--sandbox",
        "read-only",
        "-C",
        str(workspace),
        "-m",
        model,
        "-o",
        str(output),
    ]
    for feature in sorted(DISABLED_FEATURES.intersection(info["features"])):
        args.extend(["--disable", feature])
    for feature in ("code_mode", "code_mode_host", "skip_host_skill_discovery"):
        args.extend(["--enable", feature])
    config = {
        "model_catalog_json": str(run_dir / "model-catalog.json"),
        "cli_auth_credentials_store": "file",
        "web_search": "disabled",
        "project_doc_max_bytes": 0,
        "skills.include_instructions": False,
        "skills.bundled.enabled": False,
        "memories.use_memories": False,
        "memories.generate_memories": False,
        "approval_policy": "never",
        "model_reasoning_effort": effort,
        "developer_instructions": "Complete the user's task using only the supplied task tools. Give a natural-language final answer. Do not assume access to tools that are not provided." + ("\n" + task_instructions if task_instructions else ""),
    }
    mcp_servers = {}
    mcp_servers["task"] = {
        "command": sys.executable,
        "args": ["-m", "mrbench", "mcp", "--run-dir", str(run_dir)],
        "required": True,
        "startup_timeout_sec": 20,
        "tool_timeout_sec": 15,
        "default_tools_approval_mode": "approve",
    }
    config["mcp_servers"] = mcp_servers
    # Optional programmatic provider configuration also enables local protocol smoke tests.
    # It cannot override the tool or isolation profile.
    provider = info.get("provider_config", {})
    if set(provider) - {"model_provider", "model_providers"}:
        raise ValueError("Provider config may only set model_provider/model_providers")
    config.update(provider)
    for key, value in config.items():
        args.extend(["-c", f"{key}={toml(value)}"])
    args.append("-")
    return args


def execute(
    args: list[str], prompt: str, workspace: Path, prefix: Path, timeout: int,
    *, code_mode_host: str | None = None, use_auth: bool = True,
) -> dict:
    # Use the product's runtime-home setting only for this child process. Do not
    # change the caller's HOME/CODEX_HOME, global config, or personal instructions.
    # The temporary runtime contains no skills, AGENTS.md, memories or connectors.
    auth_source = (
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "auth.json"
    )
    with tempfile.TemporaryDirectory(prefix="mrbench-codex-") as runtime_dir:
        runtime_home = Path(runtime_dir)
        if use_auth and auth_source.is_file():
            (runtime_home / "auth.json").symlink_to(auth_source.resolve())
        child_environment = os.environ.copy()
        if not use_auth:
            for key in ("OPENAI_API_KEY", "CODEX_API_KEY"):
                child_environment.pop(key, None)
        child_environment["CODEX_HOME"] = str(runtime_home)
        if code_mode_host:
            # Resolve the vendor companion only for this child, without changing the caller.
            child_environment["PATH"] = str(Path(code_mode_host).parent) + os.pathsep + child_environment.get("PATH", "")
        return _execute(args, prompt, workspace, prefix, timeout, child_environment)


def _execute(
    args: list[str],
    prompt: str,
    workspace: Path,
    prefix: Path,
    timeout: int,
    child_environment: dict,
) -> dict:
    return execute_process(args, prompt, workspace, prefix, timeout, child_environment)


def inspect_stream(path: Path, *, allow_mcp: bool) -> dict:
    events, errors, forbidden, warnings = [], [], [], []
    if not path.exists():
        return {
            "completed": False,
            "errors": ["Codex event stream is missing"],
            "forbidden": [],
            "warnings": [],
        }
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"Malformed JSONL on line {number}")
            continue
        if not isinstance(event, dict):
            errors.append(f"Invalid event object on line {number}")
            continue
        events.append(event)
        if event.get("type") in ("turn.failed", "error"):
            errors.append(event.get("message") or str(event.get("error", event)))
        item = event.get("item", {})
        if not isinstance(item, dict):
            errors.append(f"Invalid item on line {number}")
            continue
        if item.get("type") == "error":
            message = item.get("message", "Codex reported a runtime error")
            if isinstance(message, str) and message.startswith("Under-development features enabled:"):
                warnings.append(message)
            else:
                errors.append(message)
        if item and item.get("type") not in (
            "agent_message",
            "reasoning",
            "todo_list",
            "mcp_tool_call",
            "error",
        ):
            forbidden.append(item.get("type"))
        if item.get("type") == "mcp_tool_call" and (
            not allow_mcp or item.get("server") != "task"
        ):
            forbidden.append(f"MCP server: {item.get('server')}")
    return {
        "completed": any(e.get("type") == "turn.completed" for e in events),
        "errors": errors,
        "warnings": warnings,
        "forbidden": sorted(set(forbidden)),
        "usage": next(
            (
                e.get("usage")
                for e in reversed(events)
                if e.get("type") == "turn.completed"
            ),
            None,
        ),
        "event_count": len(events),
    }
