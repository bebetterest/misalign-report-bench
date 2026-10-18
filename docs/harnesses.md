# Agent harnesses

A harness drives the agent; an environment defines its simulated world. Choose either real CLI without changing cases, tool semantics, state, action scoring or answer judging. The benchmark does not implement either vendor's agent loop. Codex is the default.

## Run an episode

Install and authenticate the selected CLI, choose an account-supported model, then check its capabilities:

```sh
uv run mrbench doctor                         # Codex
uv run mrbench doctor --harness grok          # Grok Build
uv run mrbench run citation-upload --model YOUR_CODEX_MODEL
uv run mrbench run citation-upload --harness grok --model YOUR_GROK_MODEL
```

Each command uses one default sample and its main condition. `--sample`, `--condition`, `--repeat`, `--timeout`, `--max-calls`, `--effort` and the optional `--judge` work with both harnesses. `--max-calls` bounds environment calls; Grok's optional `max_turns` bounds native agent turns. Timeout handling terminates the whole CLI/MCP process group. Unsupported configuration fails before inference; launch, runtime, timeout and validation failures retain their evidence with an incomplete/invalid status.

Use `--harness-executable /absolute/path/to/cli` when needed. Existing `--codex` commands remain supported for Codex. Optional TOML configuration:

```toml
[harness.codex]
# executable = "/path/to/codex"

[harness.grok]
# executable = "/path/to/grok"
max_turns = 50
```

Native login credentials are reused without copying personal settings. Grok copies only file-backed `auth.json` into a temporary home with owner-only permissions; Codex retains its existing temporary-home login link. Keyring-only authentication is unverified. Model execution uses the selected provider's quota. Judge configuration and its literal `--env-file` loader are separate; the benchmark never uses judge settings as an actor fallback.

To override Grok's native actor endpoint, explicitly set the following in `[harness.grok]`. Omit all four to use native model routing:

```toml
base_url = "https://your-actor-endpoint.example/v1"
api_backend = "responses" # also chat_completions or messages
api_key_env = "XAI_API_KEY"
max_output_tokens = 8192
```

Set the named credential in the process environment. For this explicit route, the temporary runtime does not reuse native login files and passes the selected credential through a private environment alias, keeping native login files and standard xAI credential variables out of that route. Endpoint URLs cannot contain credentials, query strings or fragments. API/backend/key/output overrides require an explicit `base_url`. This route uses Grok Build as the harness and the explicitly selected endpoint as the model provider. Record and review that distinction when reporting results.

## Reference boundaries

| Profile | Tool path | Isolation and evidence |
| --- | --- | --- |
| `codex-mcp-closed-v4` | Real `codex exec` → native Code Mode → `task` MCP | Existing feature/flag checks, temporary home, excluded personal/project instructions, bundled model catalog with host editing/experimental tools removed, native event validation |
| `grok-mcp-closed-v1` | Real `grok` → native `search_tool` / `use_tool` → `task` MCP | Temporary home and workspace outside the repository; compatibility discovery, memory, workflows, remote config fetch and telemetry disabled; actual context inspection; only task tools; explicit host Read/Bash/Edit/Write/WebFetch denial |

Grok's temporary home alone does not exclude `~/.agents/skills`. The profile also ignores the user's home in skill discovery and runs `grok inspect --json` both before a batch and before each episode. Extra instructions, hooks, skills, personal agents, plugins, LSP/MCP servers, external config layers or ignored settings cause failure. The CLI's file-backed `use_tool` input mode requires host Read permission and is denied; only inline task-tool arguments are valid. Backend web search and subagents are disabled and checked in the native stream.

These profiles restrict model tools; they are not an OS sandbox for hostile CLI binaries or environment extensions. Install trusted native CLIs. CLI versions evolve, so capability checks and installed-version protocol checks are required. Native Grok title/dashboard side calls may consume provider usage outside the actor's normalized usage. Retained raw logs can aid inspection; placeholder cost values are not a billing estimate. Live Grok model behavior and keyring authentication require separate validation.

## Record and compare

New records use `origin=agent` or `origin=protocol-check`, with schema 2. They save harness ID, native CLI version, reference profile, adapter source hash, effective configuration and native logs. Saved configuration artifacts are hash-bound. Existing `codex` / `codex-smoke` schema-1 records remain readable in the viewer; reading does not migrate or rewrite them.

The viewer displays the harness and exports the corresponding native logs. Compatible comparisons separate different harnesses, CLI/profile/adapter versions, model/provider configurations and returned actor model identities when available. Protocol fixtures, demos and incomplete runs never become model results. Reproduction commands select the recorded harness; restore the corresponding code and local TOML settings before rerunning. Re-scoring reuses saved evidence and makes no agent call.

## Add another adapter

1. Add one module in `src/mrbench/harnesses/` with an explicit ID and source modules to hash. Register it in `REGISTRY`; extend TOML option validation for its supported settings.
2. Implement `preflight(HarnessConfig) -> HarnessInfo`. Validate required installed CLI capabilities and context isolation before inference. Return sanitized version/profile/settings and configuration artifacts. Runtime-only credential handling belongs in `HarnessInfo.runtime`, never persisted credentials.
3. Implement `run(Episode) -> HarnessResult`. Use the native agent loop and the existing MCP stdio command. The episode exposes only the actor task, trusted tool policy, tool names and runtime settings. Return process status, normalized completion/errors/forbidden-tools/usage, and the final natural-language answer (or write `answer.txt`). Use shared process supervision, save native diagnostics as `<id>.jsonl` and `<id>.stderr.log`, and put sanitized configuration in `harness-*.json` artifacts. The common runner binds those artifacts and the viewer automatically exports/displays the native logs.
4. Add native parser, launch/timeout/isolation, evidence/export/comparison and localhost protocol checks. Do not pass rubric, expected answers, action scores or hidden environment state into the harness. Keep case/environment code and the independent single-request judge unchanged.

No plugin framework or new transport is necessary. If a future harness cannot use MCP stdio, adapt tool definitions/calls at its boundary while keeping the same environment contract and event recorder.

## Verify without a model API

```sh
uv run python -m unittest discover -s tests -v
uv run python tools/smoke_harness.py --harness codex --trace unsafe --runs .cache/protocol-check
uv run python tools/smoke_harness.py --harness grok --trace unsafe --runs .cache/protocol-check
uv run python tools/smoke_harness.py --harness grok --trace safe --probe-host-file --runs .cache/protocol-check
```

The scripted responder lives on localhost. These checks start the real installed CLI and MCP process, validate the runtime tool catalog and compare exact events/state/action scores with direct fixture execution. Actor and auxiliary requests receive authored responses; real actor/judge APIs are not called. Passing this check establishes transport and isolation behavior for the tested CLI and trace, not model quality or incident rates.

Primary references: [Grok headless mode](https://docs.x.ai/build/cli/headless-scripting), [Grok settings](https://docs.x.ai/build/settings), [Grok MCP](https://docs.x.ai/build/features/mcp-servers), [Codex CLI](https://developers.openai.com/codex/cli/), [Codex MCP](https://developers.openai.com/codex/mcp/).
