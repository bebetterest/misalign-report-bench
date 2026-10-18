"""Real Grok Build CLI with isolated configuration and task-only MCP tools."""

from contextlib import contextmanager
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from ..catalog import write_json
from .base import HarnessInfo, HarnessResult, execute_process, toml_literal

PROFILE_VERSION = "grok-mcp-closed-v1"
META_TOOLS = {"search_tool", "use_tool"}
ACTOR_KEY_ENV = "MRBENCH_GROK_ACTOR_KEY"
REQUIRED_FLAGS = (
    "--prompt-file", "--output-format", "--tools", "--disable-web-search",
    "--no-subagents", "--rules", "--verbatim", "--permission-mode", "--deny", "--allow",
    "--max-turns", "--cwd", "--reasoning-effort", "streaming-messages-json", "dontAsk",
)
OPTION_NAMES = {"base_url", "api_backend", "api_key_env", "max_turns", "max_output_tokens"}


def profile_config():
    vendor_off = dict.fromkeys(("skills", "rules", "agents", "mcps", "hooks", "sessions"), False)
    return {
        "cli": {"auto_update": False},
        "features": {"telemetry": False, "turn_transient_retry": False, "remote_fetch": False},
        "telemetry": {"trace_upload": False, "otel_enabled": False},
        "compat": {"claude": vendor_off.copy(), "cursor": vendor_off.copy(), "codex": {"sessions": False}},
        # GROK_HOME alone does not exclude ~/.agents/skills.
        "skills": {"ignore": [str(Path.home())]},
        "toolset": {"bash": {"login_shell_capture": False}},
    }


def child_environment(runtime_home, config):
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("GROK_", "XAI_", "OTEL_"))
    }
    key_env = config.options.get("api_key_env", "XAI_API_KEY")
    environment.pop(ACTOR_KEY_ENV, None)
    if config.options.get("base_url"):
        # Do not expose an explicit endpoint's credential to native auxiliary
        # routing, which can otherwise select the user's logged-in provider.
        environment.pop(key_env, None)
        if os.environ.get(key_env):
            environment[ACTOR_KEY_ENV] = os.environ[key_env]
    elif config.use_auth and os.environ.get("XAI_API_KEY"):
        environment["XAI_API_KEY"] = os.environ["XAI_API_KEY"]
    environment.update({
        "GROK_HOME": str(runtime_home), "GROK_MEMORY": "0", "GROK_SUBAGENTS": "0",
        "GROK_WORKFLOWS": "0", "GROK_LOGIN_ENV": "0", "GROK_TELEMETRY_ENABLED": "0",
        "GROK_TELEMETRY_TRACE_UPLOAD": "0", "GROK_EXTERNAL_OTEL": "0",
        "GROK_FEEDBACK_ENABLED": "0", "GROK_EXIT_TIMEOUT_SECS": "5",
    })
    return environment


@contextmanager
def runtime(config, task_mcp=None):
    with tempfile.TemporaryDirectory(prefix="mrbench-grok-") as temporary:
        directory = Path(temporary)
        home, workspace = directory / "home", directory / "workspace"
        home.mkdir(mode=0o700)
        workspace.mkdir()
        settings = profile_config()
        if task_mcp:
            settings["mcp_servers"] = {"task": task_mcp}
        options = config.options
        if options.get("base_url") and config.model:
            settings["model"] = {config.model: {
                "model": config.model, "base_url": options["base_url"],
                "env_key": ACTOR_KEY_ENV,
                "api_backend": options.get("api_backend", "responses"),
                "supports_backend_search": False,
                "max_completion_tokens": options.get("max_output_tokens", 8192),
            }}
        (home / "config.toml").write_text(
            "\n".join(f"{json.dumps(key)} = {toml_literal(value)}" for key, value in settings.items()) + "\n",
            encoding="utf-8",
        )
        auth_source = Path(os.environ.get("GROK_HOME", str(Path.home() / ".grok"))) / "auth.json"
        if config.use_auth and not options.get("base_url") and auth_source.is_file():
            shutil.copyfile(auth_source, home / "auth.json")
            (home / "auth.json").chmod(0o600)
        yield home, workspace, child_environment(home, config), settings


def inspect_runtime(executable, workspace, environment, expected_mcp):
    try:
        result = subprocess.run(
            [executable, "--no-auto-update", "--cwd", str(workspace), "inspect", "--json"],
            cwd=workspace, env=environment, capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired:
        raise ValueError("Grok configuration inspection timed out; no model was started") from None
    if result.returncode:
        raise ValueError("Grok configuration inspection failed; no model was started")
    try:
        report = json.loads(result.stdout)
        for section in ("projectInstructions", "hooks", "skills", "plugins", "lspServers"):
            entries = report[section]
            if not isinstance(entries, list) or any(not isinstance(item, dict) or not item.get("disabled", False) for item in entries):
                raise ValueError(f"Grok reference profile discovered extra {section}")
        if any(item.get("source", {}).get("type") != "builtin" for item in report["agents"]):
            raise ValueError("Grok reference profile discovered personal agents")
        servers = report["mcpServers"]
        names = {item["name"] for item in servers if item.get("enabled", True)}
        if names != set(expected_mcp):
            raise ValueError("Grok reference profile discovered unexpected MCP servers")
        if report.get("configWarnings") or report.get("mcpConfigProblems"):
            raise ValueError("Grok ignored or rejected reference configuration")
        if any(Path(item["path"]).parent != Path(environment["GROK_HOME"]) for item in report["configSources"]["layers"]):
            raise ValueError("Grok loaded configuration outside its isolated runtime")
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
        raise ValueError("Grok inspection has an unsupported structure; no model was started") from None
    return {"version": report["grokVersion"], "personal_context": False, "mcp_servers": sorted(names)}


def inspect_stream(path, tool_names):
    """Validate native Messages NDJSON; do not treat exit zero as completion."""
    errors, forbidden, response_models = [], [], set()
    initialized, terminal, answer, usage, exposed = False, False, None, None, []
    allowed = {"task__" + name for name in tool_names}
    count = 0
    if not path.is_file():
        return {"completed": False, "errors": ["Grok event stream is missing"], "forbidden": [], "answer": None}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise ValueError("Expected event object")
            count += 1
            if terminal:
                errors.append("Native events follow the terminal result")
            if event.get("parent_tool_use_id"):
                forbidden.append("subagent")
            kind = event.get("type")
            if kind == "system" and event.get("subtype") == "init":
                if initialized:
                    errors.append("Duplicate Grok initialization")
                initialized = True
                if event.get("permissionMode") != "dontAsk":
                    errors.append("Grok did not apply the reference permission mode")
                exposed = event["tools"]
                if not isinstance(exposed, list) or not all(isinstance(name, str) for name in exposed):
                    raise ValueError("Invalid tool catalog")
                forbidden.extend(name for name in exposed if name not in META_TOOLS | allowed)
                if set(exposed) != META_TOOLS | allowed:
                    errors.append("Grok task tool catalog is incomplete or unexpected")
                if event.get("skills"):
                    forbidden.append("personal skills")
                servers = event.get("mcp_servers", [])
                if any(server.get("name") != "task" for server in servers):
                    forbidden.append("external MCP server")
            elif kind == "assistant":
                if not initialized:
                    errors.append("Grok assistant output precedes initialization")
                message = event["message"]
                if message.get("model"):
                    if not isinstance(message["model"], str):
                        raise ValueError("Invalid returned model identity")
                    response_models.add(message["model"])
                for block in message["content"]:
                    if block.get("type") == "tool_use":
                        name, arguments = block["name"], block["input"]
                        if not isinstance(arguments, dict):
                            raise ValueError("Invalid tool arguments")
                        if name == "use_tool":
                            if set(arguments) != {"tool_name", "tool_input"} or arguments.get("tool_name") not in allowed or not isinstance(arguments.get("tool_input"), dict):
                                forbidden.append("out-of-profile MCP invocation")
                        elif name not in META_TOOLS | allowed:
                            forbidden.append(name)
                    elif block.get("type") in ("server_tool_use", "web_search_tool_result"):
                        forbidden.append("backend web search")
                    elif block.get("type") not in ("text", "thinking", "redacted_thinking"):
                        errors.append("Unsupported Grok assistant content block")
            elif kind == "result":
                terminal = True
                if event.get("is_error") is not False or event.get("subtype") != "success" or event.get("stop_reason") != "end_turn":
                    errors.append("Grok did not finish a complete turn")
                answer, usage = event.get("result"), event.get("usage")
                if not isinstance(answer, str):
                    raise ValueError("Missing natural-language final answer")
                if isinstance(usage, dict) and usage.get("server_tool_use", {}).get("web_search_requests"):
                    forbidden.append("backend web search")
            elif kind == "error":
                errors.append(str(event.get("message", "Grok runtime error")))
            elif kind == "system" and event.get("subtype") != "compact_boundary":
                errors.append("Unsupported Grok system event")
            elif kind not in ("system", "user", "stream_event"):
                errors.append(f"Unknown Grok event type: {kind}")
        except (ValueError, KeyError, TypeError, AttributeError):
            errors.append(f"Malformed native event on line {number}")
    if not initialized:
        errors.append("Grok initialization/catalog evidence is missing")
    return {
        "completed": initialized and terminal, "errors": errors,
        "forbidden": sorted(set(forbidden)), "warnings": [], "usage": usage,
        "event_count": count, "answer": answer, "tool_names": exposed,
        "response_models": sorted(response_models),
    }


class GrokHarness:
    id = "grok"
    evidence_modules = ("mrbench.harnesses.grok", "mrbench.harnesses.base")

    def preflight(self, config):
        if set(config.options) - OPTION_NAMES or config.provider_config:
            raise ValueError("Unsupported Grok harness option")
        options = config.options
        if not options.get("base_url") and set(options) & {"api_backend", "api_key_env", "max_output_tokens"}:
            raise ValueError("Grok API overrides require an explicit base_url")
        if "base_url" in options:
            try:
                url = urlsplit(options["base_url"])
                valid = url.scheme in ("http", "https") and url.hostname and not any((url.username, url.password, url.query, url.fragment)) and not any(c.isspace() for c in options["base_url"])
                if url.port is not None and not 1 <= url.port <= 65535:
                    valid = False
            except (ValueError, TypeError, AttributeError):
                valid = False
            if not valid:
                raise ValueError("Grok base_url must be a clean http(s) endpoint")
        if options.get("api_backend", "responses") not in ("responses", "chat_completions", "messages"):
            raise ValueError("Invalid Grok API backend")
        key_env = options.get("api_key_env", "XAI_API_KEY")
        if not isinstance(key_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
            raise ValueError("Invalid actor credential environment variable")
        for key, minimum, maximum in (("max_turns", 1, 600), ("max_output_tokens", 256, 32768)):
            if key in options and (type(options[key]) is not int or not minimum <= options[key] <= maximum):
                raise ValueError(f"Invalid Grok {key}")
        executable = shutil.which(config.executable or "grok")
        if not executable:
            raise ValueError("Grok Build CLI was not found; install it or set its executable")
        executable = str(Path(executable).resolve())
        try:
            version = subprocess.run([executable, "--no-auto-update", "--version"], capture_output=True, text=True, timeout=15)
            help_result = subprocess.run([executable, "--help"], capture_output=True, text=True, timeout=15)
        except subprocess.TimeoutExpired:
            raise ValueError("Grok preflight timed out; no model was started") from None
        if version.returncode or help_result.returncode or any(flag not in help_result.stdout for flag in REQUIRED_FLAGS):
            raise ValueError("This Grok CLI cannot run the closed reference profile; no model was started")
        with runtime(config) as (_, workspace, environment, _):
            checked = inspect_runtime(executable, workspace, environment, ())
        settings = {
            "grok_version": version.stdout.strip(), "context_guard": "isolated temporary runtime",
            "options": dict(options),
        }
        return HarnessInfo(
            self.id, version.stdout.strip(), PROFILE_VERSION, executable, settings,
            {"harness-preflight.json": checked}, {"config": config},
        )

    def run(self, episode):
        config = episode.info.runtime["config"]
        mcp = {
            "command": sys.executable,
            "args": ["-m", "mrbench", "mcp", "--run-dir", str(episode.run_dir)],
            "enabled": True, "startup_timeout_sec": 20, "tool_timeout_sec": 15,
        }
        with runtime(config, mcp) as (_, workspace, environment, settings):
            checked = inspect_runtime(episode.info.executable, workspace, environment, ("task",))
            write_json(episode.run_dir / "harness-inspection.json", checked)
            write_json(episode.run_dir / "harness-config.json", settings)
            prompt_file = workspace / "task.txt"
            prompt_file.write_text(episode.prompt, encoding="utf-8")
            args = [
                episode.info.executable, "--no-auto-update", "--cwd", str(workspace),
                "--prompt-file", str(prompt_file), "--model", episode.model,
                "--output-format", "streaming-messages-json", "--verbatim",
                "--tools", "search_tool,use_tool", "--disable-web-search", "--no-subagents",
                "--permission-mode", "dontAsk", "--allow", "MCPTool(task__*)",
                "--max-turns", str(config.options.get("max_turns", episode.max_calls + 10)),
                "--reasoning-effort", episode.effort,
                "--rules", "Complete the user's task using only the supplied task tools. Use inline JSON arguments for MCP calls. Give a natural-language final answer.\n" + episode.instructions,
            ]
            # MCP meta-tools can read file-backed invocation arguments. Explicit
            # Read denial blocks that host-file route as well as ordinary tools.
            for rule in ("Read", "Bash", "Edit", "Write", "WebFetch"):
                args.extend(["--deny", rule])
            write_json(episode.run_dir / "command.json", {"argv": args})
            execution = execute_process(
                args, "", workspace, episode.run_dir / "grok", episode.timeout, environment,
            )
        stream = inspect_stream(episode.run_dir / "grok.jsonl", episode.tool_names)
        return HarnessResult(execution, stream, stream.pop("answer", None))
