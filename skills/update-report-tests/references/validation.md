# Validation and evidence

Use a new ignored output directory for each review or revised input set. Commands below run from the repository root; replace `REVIEW_ID` and `CASE_ID`. Inspect current `--help` before adapting flags. Use the existing locked environment; avoid unrelated dependency upgrades.

## Select checks by what changed

| Change | Meaningful checks |
| --- | --- |
| Discovery selectors, source metadata or mappings | Source-registry tests, `validate`, `coverage`; exercise added/changed/missing entries and fetch/parse failures when discovery logic changes. Preserve unresolved evidence. |
| Task data, tools, permissions or controls | Exact actor-surface review, affected environment/scenario tests and authored safe/counterexample traces across the affected conditions. Verify fresh state and normal task paths. |
| Rubric, completion or final-output extraction | Correct, incorrect, honest-blocker, missing/blank/wrong-deliverable references; inspect actual judge inputs and necessary state predicates. Run grading/output/evidence regressions. |
| Shared environment, scorer or harness | Full offline regression and affected environment families. Use current-hash real-Codex protocol checks when tool surfaces, transport, runner or trusted instructions change. |
| New output presentation or viewer behavior | Actual list/detail/export, empty/error and safe-text rendering checks on desktop/mobile; inspect task/condition labels, score states and compatibility groups. |
| Packaging or new public resources | Build and inspect wheel/sdist, check relative links and exclusion of local material, then verify affected installed resources. Repository skills belong in the source archive; wheel runtime resources have a separate boundary. |

Do not repeat broad checks after an unchanged successful result without a new failure or concern. A passing fixture should exercise a meaningful causal property, not mirror the implementation or merely match documentation wording.

## Review fixture meaning before hashes

The main report fixture is [report-scenarios.json](../../../tests/fixtures/report-scenarios.json); the separate lake suite is [judge-quality-citation-upload.json](../../../tests/fixtures/judge-quality-citation-upload.json). Review affected `safe`/`unsafe` tool traces, `mechanism_checks`, `answer_expectations`, additional `answer_checks` and final `output_trace` contents against the task and source. Trace names describe action examples, not guaranteed answer completion.

After semantic review, bind `target_hashes` / suite targets using the project's canonical `mrbench.catalog.digest` of the current case/sample, and update the appropriate reference version. Metadata-only edits can also change hashes. Review `label_provenance`: authored expectations remain authored development references. Do not invent independent human review, recalculate old run bindings or use a migration script from local notes as a generic rebinder.

Add discriminating expectations for a changed mechanism: equal-to-threshold exclusion, a failed action with persistent prior effects, a real availability control, a required checker invocation, a wrong delivered file despite a correct chat answer, or a nonblank checkpoint. Use the relevant properties instead of adding every example to every case.

## Offline validation first

```sh
uv run mrbench validate
uv run mrbench coverage
uv run python tools/review_scenarios.py --case CASE_ID --output .cache/report-update/REVIEW_ID/actor-surfaces.json
```

For cases present in the report fixture:

```sh
uv run python tools/check_environments.py --case CASE_ID --output .cache/report-update/REVIEW_ID/environments.json
```

The report checker excludes the separate lake environment. Use its environment/extension tests when changing that case. Select relevant unittest modules, and run the full suite for shared behavior or the final inclusion check when needed:

```sh
uv run python -m unittest discover -s tests -v
```

Check the actual coverage before claiming a variant was validated:

| Tool | Coverage boundary |
| --- | --- |
| Surface exporter | All samples and conditions of selected cases; dynamic tool results still need inspection. |
| Environment checker | The fixture's nominated sample and all conditions unless filtered. Detailed `mechanism_checks` apply to `main`; `enforced` checks that no violation commits. Add explicit assertions for other controls and additional samples. |
| Report judge checker | The fixture's nominated sample; baseline answers use the default condition, with extra conditions only through explicit `answer_checks`. |
| Codex protocol checker | One fixture sample and selected/default condition per invocation. A selected probe does not cover the other variants. |

The environment/judge/protocol scripts use the packaged catalog and do not accept `--cases`. For an alternative library, use CLI `validate`/`coverage` with matching `--cases` and `--sources`, the surface exporter's `--cases`, and explicit environment tests. Do not describe packaged checks as custom-library validation.

Prepare answer inputs without credentials or API requests; select affected report cases, or use `--all` for a shared rubric change:

```sh
uv run python tools/check_report_judges.py --case CASE_ID --config mrbench.example.toml --prepare-only --output .cache/report-update/REVIEW_ID/report-judge
uv run python tools/check_judge.py --config mrbench.example.toml --prepare-only --output .cache/report-update/REVIEW_ID/lake-judge
```

Run the lake command when that suite is affected. Inspect final delivered texts, task/fact consistency, inapplicable fields, evidence excerpts and completion criteria. Expected labels and reference construction traces must stay outside API input. Extract only the declared final deliverable texts; do not append raw state objects, credentials or action verdicts as extra evidence. Required artifacts and actual task effects have their own objective checks.

## Separate transport, judge quality and actor behavior

When the selected report trace and installed CLI support it:

```sh
uv run python tools/smoke_harness.py --harness codex --case CASE_ID --trace unsafe --runs .cache/report-update/REVIEW_ID/protocol
```

This starts real Codex/Code Mode/MCP with scripted localhost model responses. Check environment/framework/input hashes against the final edited checkout. If a later shared module or tool policy changes, prior probes are older evidence. The probe establishes transport/tool-boundary behavior, not an actor's propensity. The lake case uses its own built-in query/upload trace; `--trace` also selects its safe or unsafe path.

Real judge checks make one API request per selected reference. Before executing, establish that the requested run/configuration and cost are authorized. Use the separately configured judge and literal `--env-file` loader; do not print, shell-source or export judge-only credentials to the actor. Keep labels and action evidence isolated. A mismatch, refusal, truncation, malformed output, unsupported evidence or low-confidence result stays a disagreement/error/review item. Do not retry or change labels silently to obtain agreement.

Actual actor episodes also require scope-appropriate authorization. Choose cases, samples, controls, model, repeats, output location and stopping conditions before launch. Reuse the real CLI harness and fresh worlds; do not simulate a model result with authored traces. Keep API errors, incomplete episodes, unavailable model versions and historical inputs visible and separate. Do not treat observing a violation as an engineering acceptance requirement.

## Preserve and report the evidence

Keep source checks, adaptation working notes, raw requests/responses, run logs and screenshots in ignored `.cache/`, `runs/` or `.local/` paths. Preserve failed and successful checks separately. Never rewrite historical run prompts, contexts, outputs, scores or manifests to match a new test; explicit rescoring uses frozen evidence and preserves prior scores. Package inspection must exclude credentials, full cached reports, local notes and history backups.

Finish with the reviewed sources and cutoff, case/component mapping decisions, changed versions, exact checks and their scope, unresolved source/abstraction questions, and live validation still pending. Inspect the final diff, public links and case counts dynamically. Do not describe fixed development-reference agreement as a calibrated error rate, or scripted replay as real model behavior. Only compatible completed real actor runs enter model comparisons, with valid denominators per metric.

When harness or shared runner contracts change, repeat the affected protocol traces with `--harness grok` as well as Codex, verify exact environment events/state and test Grok’s `--probe-host-file` denial. Harness identity, adapter/profile versions and returned model identities are comparison boundaries. Do not rewrite legacy evidence to the new record schema; see [harnesses](../../../docs/harnesses.md).
