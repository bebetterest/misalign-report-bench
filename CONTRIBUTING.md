# Contributing

MisalignReportBench converts public reports into inspectable evaluations. A contribution should make its source, abstraction, authorization boundary and scoring logic easy to review. Keep code, documentation, task text, fictional data and UI copy in English.

## From report to benchmark case

For a source-driven update, follow the [update-report-tests skill](skills/update-report-tests/SKILL.md), which applies this checklist using the existing discovery, scenario-review and validation tools.

1. **Register the source.** Record the original URL, publisher, update date, incident dates and the precise example being adapted. Preserve attribution and redistribution terms.
2. **Extract the mechanism.** Identify the ordinary task, available tools, observable problematic action and authorization boundary. Separate reported observations from your interpretation.
3. **Choose task boundaries and build minimal tests.** One report can yield several cases when it contains distinct work requests or independently testable threats. State what each preserves, simplifies and leaves out. Start each case with one sample and controlled changes that isolate the variable of interest.
4. **Verify scoring.** Exercise correct execution, attempted and successful boundary violations, failed operations and authorized controls. Review correct, incorrect, refused and uncertain answer examples against the rubric.
5. **Review and include.** Check validity, evidence, isolation and documentation before registering a release. Adding a report does not require changing the Codex agent loop.

## Contribution checklist

- [ ] The source is public, linked and scoped to a specific example; its dates and attribution are recorded.
- [ ] The website is registered in `source-coverage.json`; its dated `sources/*.json` snapshot maps each adapted component and preserves its evidence status. Uncertain attribution, unverified and legitimate examples are not relabelled as confirmed incidents.
- [ ] Source changes are reviewed explicitly. Discovery never rewrites cases or historical results; supporting sources retain independent attribution.
- [ ] Case boundaries follow independent tasks or threats, not article count. Data variants use samples; authorization/availability changes use conditions. Connected stages of one failure remain a trace unless they can be meaningfully tested independently. Document omitted components and avoid counting duplicate tasks as extra coverage.
- [ ] Observed behavior is distinguished from causal interpretations or claims about hidden intent.
- [ ] Task data can be redistributed. Fictional replacements are identified explicitly.
- [ ] The normal task and the user’s authorization boundary are clear. Added task requirements are documented as adaptations; undisclosed original instructions are not invented.
- [ ] Autonomous failures are not turned into explicit attack requests. Source-contained attacks stay in lower-trust input; summary-generation studies do not start with the unwanted summary already supplied.
- [ ] Normal searches and interface documentation do not reveal an exploit recipe, private-read command or magic benchmark label. Source-task substitutions and limited runtime models remain visible in `scenario_review`.
- [ ] Completion criteria match the task. Optional diagnostics do not become hidden task requirements; voluntary verification claims are checked for support.
- [ ] A case starts with one default sample; additional samples vary task data and remain separately versioned.
- [ ] Conditions and repeated trials are distinct from samples. Controls change only the stated variable, retaining legitimate task data, source references and tool access. Available-data controls must provide actual readable evidence, not just changed judge expectations.
- [ ] Any adversarial instructions are deliberate lower-trust test material, identified in the abstraction. Ordinary task prompts and services contain no unintended solution hints or upload suggestions.
- [ ] Every episode has independent state. Normal operations, strict thresholds and failure paths behave correctly.
- [ ] Attempts and successes have distinct instrumentation where failures are possible; the scorer checks events against final state.
- [ ] Inconsistent or incomplete evidence is unscored, not a pass.
- [ ] Required artifacts/state transitions have objective predicates, checked against current contents. Correct text alone does not complete an unfinished deployment, inbox, build or migration. Empty handoffs do not count as delivered text; positive judge responses for absent/blank required texts must remain review-required without retrying.
- [ ] Shared behavior modules are hash-bound; safe/counterexample traces check replay, failure persistence, authorized controls and independent episodes.
- [ ] Simulated tools never touch real hosts, credentials, wallets, package registries or messaging services.
- [ ] The agent may answer naturally; the judge rubric accepts reasonable paraphrases.
- [ ] The answer judge receives the final answer, declared final task texts and trusted task context, makes one API request and never grades unseen actions. Output selectors must expose actual delivered text, without events, action scores or service state.
- [ ] Rubric examples and mechanism assertions are explicitly reviewed and labelled. Record whether independent human review exists; authored development references are not human calibration.
- [ ] Run origins, versions, effective configurations and limitations remain visible; comparisons exclude demos and incompatible runs.
- [ ] English documentation, source links, examples and browser states are updated. Logs render as text.

## Local checks

```sh
uv sync --locked
uv run mrbench validate
uv run python -m unittest discover -s tests -v
uv run python tools/check_environments.py
uv run python tools/review_scenarios.py --output .cache/actor-surfaces.json
uv build --wheel
```

For changes to Codex/MCP integration, also run:

```sh
uv run python tools/smoke_codex.py --case citation-upload
# Repeat with each changed case ID.
```

This protocol check uses the real CLI and a scripted localhost responder. It does not run a real model or an external judge. Keep those three kinds of evidence separate: offline checks, live integration checks and model behavior results.

The surface exporter is a manual review aid, not a semantic fidelity check. Choose a new output path for each review; it keeps trusted instructions separate from authored lower-trust workspace/session/message material and excludes answer rubrics and hidden service state.

For viewer changes, check list/detail interactions, copy/export, empty and error states, desktop/mobile layout, keyboard focus and safe rendering of untrusted answers. Keep execution logs and review captures in `.local/`; describe reproducible checks in the [testing guide](docs/testing.md).

For a new source website, follow [source registration](docs/sources.md). Standard HTML discovery uses JSON selectors; add an adapter only for another format. Exercise added/changed/missing entries, fetch/selector failures and offline coverage.

## Version rules

- **Record schema:** increment `schema_version` for incompatible artifact structure changes. Do not invent missing evidence when opening an older record.
- **Case:** update `case.json` version when the mechanism, authorization boundary, tool behavior, task language or interpretation changes. Explain comparability limits.
- **Sample:** update the sample version when its prompt, data, names, threshold or expected facts change. Keep stable IDs when it is still the same sample lineage.
- **Harness/framework:** update the package version for shipped changes. Runs record package/Codex versions, effective configuration and implementation hashes.
- **Scoring:** preserve old scores in history. Action review requires the recorded environment implementation; answer review uses saved answers and frozen judge context. Model aliases and provider configuration can drift, so record the effective settings.

Never pool results merely because case IDs or model names match. The viewer groups real completed runs using their recorded version/configuration hashes and applies valid denominators separately for each metric.

Before publication, review the report’s terms, dataset redistribution rights, credential handling and the distinction between a simplified benchmark result and the original report. Code and self-authored fictional data are [MIT licensed](LICENSE); upstream sources and assets retain their own terms.

## Keep working records local

Use `.local/` for diaries, handoffs, execution logs, troubleshooting transcripts, browser QA, naming discussions and maintenance/history backups. These records must stay out of commits and distribution archives, including earlier revisions. Public documentation should describe the current product, source mapping, assumptions, extension points and reproduction methods. Keep generated benchmark runs and grading evidence under the ignored `runs/` or `.cache/` directories.
