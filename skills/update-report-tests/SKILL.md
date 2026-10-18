---
name: update-report-tests
description: Review new or revised reports on MisalignReportBench's registered source websites and update affected benchmark cases, samples, environments, rubrics, and checks. Use for a requested source refresh or report-derived test update.
---

# Update report-derived tests

Convert reviewed source changes into reproducible tests, preserving the ordinary task, selected threat, authorization boundary and evidence limits. Reuse the existing environments and real-Codex harness.

## Scope and setup

Work from the repository root with its locked environment (`uv sync --locked` if setup is needed). Read applicable instructions, `git status` and [the source workflow](../../docs/sources.md). Use the user's selected providers, articles, cases and date range; otherwise use the registered providers in [source-coverage.json](../../src/mrbench/source-coverage.json). Derive versions, counts and CLI capabilities from the checkout.

Read supporting material as needed without registering additional websites. The skill also works in a fresh clone; local notes are optional and may contain superseded checkpoints. Update manually unless scheduling was requested. Existing authorization applies within its stated scope; the skill itself does not authorize paid calls, publication or history changes.

## Update workflow

1. **Inspect the baseline.** Run `uv run mrbench sources list` and `uv run mrbench coverage`. Locate source/component mappings and affected cases, samples, conditions, environment modules and reference fixtures. Consult [architecture](../../docs/architecture.md) for unfamiliar contracts.

2. **Discover and read.** For a website refresh, select the provider and an unused `REVIEW_ID`:

   ```sh
   uv run mrbench sources check --provider transluce --content --output .cache/report-update/REVIEW_ID/source-check.json
   ```

   Use `all` for an all-provider refresh. A named article/case can be reviewed directly. The command only writes candidate changes. Read actual articles and relevant supplements before adapting them; keep raw source caches local.

3. **Decide what changed.** Separate behavioral revisions, editorial changes, missing baselines and fetch/parse failures. Preserve source kinds, dates, attribution and evidence uncertainty. `not_listed` does not prove deletion; inaccessible content remains unresolved. For reviewed editorial-only changes, update provenance/fingerprints without altering task semantics. If nothing changed, report the check without case/version churn. Keep deferred candidates local instead of inserting dummy mappings.

4. **Review the experiment.** Before changing tasks, tools, conditions or rubrics, read [scenario review](references/scenario-review.md). Extract the work goal, obstacle, capabilities, trust boundary and observable behavior. Document invented details and omissions. Split distinct tasks or independently testable threats into cases; use samples for data, conditions for controlled changes, and trials for repeats. Discuss a material task substitution unsupported by the source while continuing independent work.

5. **Apply a coherent update.** Follow [the extension guide](../../docs/extending.md) and [version rules](../../CONTRIBUTING.md#version-rules). Keep changed task/data, environment behavior, required effects, final-output selectors and reference expectations consistent. Start new cases with one default sample. Promote source metadata only after review: preserve stable identities and primary/supporting mappings, copy reviewed fingerprints, and update review dates/counts/scope accurately. Update maintained explanations when their meaning changes.

6. **Validate and report.** Follow [validation and evidence](references/validation.md), selecting checks for the changed contract and actual sample/condition coverage. Review actor surfaces, controls, state effects and answer expectations before rebinding hashes; provenance-only edits can also change case hashes. Do not silence failures by blindly refreshing bindings or weakening expectations. Report reviewed sources, changed mappings/versions, exact checks, unresolved limits and pending live validation. Distinguish offline replay, scripted real-CLI transport, real judge checks and actual actor episodes.

## Preserve these boundaries

- Autonomous failures remain unrequested; source-authentic attacks stay lower-trust, and legitimate source-requested actions remain allowed.
- Actions use event/state evidence. Attempts, committed effects and authorization remain distinct; later errors do not erase earlier effects.
- Natural answers and declared final task texts are judged in one independent API request, without trajectories, action scores or hidden service state. Required task effects are checked separately.
- Episodes have independent state. Task tools simulate services without real uploads, messages, accounts, exploitation or host credential use.
- Preserve historical evidence and failed checks. Explicit rescoring uses frozen inputs and retains prior scores; comparisons require compatible recorded inputs/configuration.
- Keep maintained content English and working records local. Inspect packaging when its contents change; commit/push only when requested.

Use [the contribution checklist](../../CONTRIBUTING.md) before inclusion. Passing authored checks does not establish incident fidelity, judge calibration or a model failure rate.
