# Testing and evidence

Use different checks for configuration, simulator behavior, transport integration and model quality. A successful scripted replay establishes engineering behavior; model and judge claims require their own reviewed evidence.

## Offline checks

From a checkout, install the locked dependencies and validate the library:

```sh
uv sync --locked
uv run mrbench validate
uv run mrbench coverage
uv run python -m unittest discover -s tests -v
uv run python tools/check_environments.py
uv build
```

`validate` checks case/sample contracts, tool schemas, defaults and source mappings. The unit suite checks state isolation, action evidence, completion requirements, judge input boundaries and viewer behavior. `check_environments.py` replays authored safe/counterexample traces against every declared condition and checks explicit response/state properties. The separate lake tests cover strict thresholds, upload permissions and persistent upload effects.

Fixture expectations are authored engineering references. They must be reviewed with the task and original source; passing them does not establish realistic incident reproduction or an actor's behavior rate.

## Harness and MCP integration

```sh
uv run mrbench doctor
uv run python tools/smoke_harness.py --harness codex --case restart-handoff --runs .cache/protocol-check
uv run mrbench doctor --harness grok
uv run python tools/smoke_harness.py --harness grok --case restart-handoff --runs .cache/protocol-check
uv run python tools/smoke_harness.py --harness grok --trace safe --probe-host-file --runs .cache/protocol-check
```

The protocol checker starts the selected real CLI and MCP transport with a scripted localhost responder. Codex retains Code Mode; Grok retains its native MCP invocation loop. Grok title/summary requests are counted separately. The host-file probe must be denied before any environment call and produce an invalid execution record. It checks the runtime tool boundary and compares exact tool events, state and action evidence with direct fixture execution. It makes no actor-model or judge API request. Unsupported CLI capabilities stop execution before inference. A selected protocol trace does not cover every task or condition through either CLI. `tools/smoke_codex.py` remains a backward-compatible Codex entry point. See [harness setup](harnesses.md) for supported profiles and limitations.

## Answer-judge references

Prepare inputs before choosing an API run:

```sh
uv run python tools/check_judge.py --config mrbench.example.toml --prepare-only
uv run python tools/check_report_judges.py --all --config mrbench.example.toml --prepare-only
```

Previewing makes no API request. The [judge quality guide](judge-validation.md) explains reference coverage, paid checks, disagreements and limits. Expected verdicts remain outside judge input. The judge receives the final answer, declared final task texts and trusted task facts, without trajectories, action scores or hidden service state. API errors and uncertain judgments never become automatic passes.

## Actual model studies

Use the [run commands](../README.md#run-a-real-codex-evaluation) for an actual actor and configure the judge independently. Keep configuration versions, frozen inputs, returned model identity, trial counts and per-metric denominators with the evidence. Demos, protocol fixtures and fixed-answer references remain separate from model results. Do not pool incompatible inputs or infer production incidence from reduced environments.

## Viewer and packaging checks

Check list/detail interactions, filters, copy/export, empty/error states, keyboard focus, safe rendering of untrusted text and desktop/mobile layout. Build the wheel and source distribution, then verify the installed CLI can locate its case data and web assets outside the source checkout.

## Local working records

Keep diaries, handoffs, execution logs, browser QA captures, maintenance notes and history backups under `.local/`. Generated evaluation records belong in the ignored `runs/` or `.cache/` directories. Public documentation describes the current interfaces, source-to-test mapping, assumptions and reproduction methods. Local work records are excluded from Git history and distribution archives.
