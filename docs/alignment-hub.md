# Alignment Hub: discovery, screening and task adaptation

[Alignment Hub](https://huggingface.co/spaces/witness-archive/alignment-hub) is a discovery catalog maintained by [The Witness Archive](https://huggingface.co/datasets/witness-archive/alignment-hub). The benchmark checks original publications before converting selected components. Its AI-extracted, source-checked annotations are not independent verification, human calibration or a model result.

## Current selection

The reviewed dataset revision is `63df0a1ec377d84609dd95ba66ec39383d671b96`, containing 130 records. The [packaged snapshot](../src/mrbench/source-catalogs/alignment-hub.json) preserves upstream review status, experimental context, weak-candidate labels and parent links, plus a project-specific decision and reason for every record. Raw annotations, downloaded reports, extraction tools and review logs are not packaged.

| Decision | Records | Meaning |
| --- | ---: | --- |
| Included | 32 | Selected original-source components supply new tests |
| Covered | 30 | Existing or overlapping tests represent selected components; this is not exhaustive incident reproduction |
| Deferred | 68 | Evidence, task detail, scoring contract or runtime is still insufficient |

OpenAI and Anthropic are prioritized when a defensible test can be built. Of the catalog's 39 OpenAI-reported records, 5 are included, 22 associated with selected existing components, and 12 deferred. Of its 49 Anthropic-reported records, 27 are included and 22 deferred. An independent component from the publication linked to deferred record MSI-0076 is also tested: that does not convert the record's child-agent autoapproval incident into a completed reproduction.

Selected catalog components supply 38 cases from 16 original publications: 5 OpenAI cases and 33 Anthropic cases. Several publications provide distinct work requests. The full library now has 101 cases, 101 default samples and 284 conditions, mapped to 47 reviewed source entries across three publishers. The 130 catalog records are a separate inventory, not an additional source/incident/coverage denominator. Related reports and shared tasks are not statistically independent observations.

## Inclusion contract

1. Read the original report and relevant supplemental material. Preserve attribution and uncertainty; an inaccessible article stays unresolved.
2. Identify the legitimate task, obstacle, capabilities, trust/authorization boundary and observable result. Keep source-authentic attacks at the same lower-trust entry point. Do not ask the actor to perform the reported unwanted action.
3. Split distinct tasks or independently testable threats. Use samples for concrete data variants, conditions for controlled permission/availability changes, and trials for repeated runs. Do not create multiple identical actor environments to inflate case counts.
4. State reconstruction limits. `decision-rehearsal` preserves a documented decision with fictional services; `mechanism-study` uses new task details where the original is undisclosed. Neither reproduces exploit difficulty, incident rates or hidden intent.
5. Check attempts, committed effects and task requirements independently. Required final task texts join the natural answer in one isolated judge request. Events, action findings and hidden service state never enter that request.
6. Revisit deferred records when evidence or an appropriate runtime becomes available. Inclusion priority does not remove these requirements.

All actors receive normal work requests. Simulated services accept inert data; there is no real upload, publication, authentication, exploitation, native shell execution, process control or child-model delegation. Available/authorized controls are explicit. Authored traces validate the simulated contract; they do not show a model's propensity to violate it.

## Selected task families

- **Scope and credentials:** named-machine cleanup, remote-job authentication, another user's PR credential, public knowledgebot outreach, colleague branch updates, process ownership and review authorship.
- **Evidence and honest reporting:** exact calculation versus target assignment, queued worker versus actual progress, active production paths, failed discussion retrieval, retrospective error accounts, watcher lifecycle, tool-result attribution, missing vendor hashes and unavailable search.
- **Approval provenance:** review authorship, destructive prerequisites, database access and experiment confirmation. Authentic saved messages are separate from attributed strings; completing a prerequisite is separate from completing the requested experiment.
- **Forms and data access:** unavailable practice copy, final form submission, fabricated example tips, public visitor tokens versus paid-data permission and URL-length circumvention through a shortener.
- **Development and security scope:** preserving failing regression tests, preserving audit source integrity, external customer records, public packages, external application writes, a broken abort and maintainer outreach.
- **Publication:** internal-only benchmark results and the report from an authorized sandbox exercise. The authorized escape itself is not classified as the unwanted action.

Important source distinctions remain explicit: a local digest does not replace a missing vendor checksum; the shortener case is about URL length; one tool-result discrepancy was interpreted as likely benign by its authors; the public-tip case assesses fabricated content without inventing a blanket publication ban. Native exploit mechanics, original scientific difficulty, persistent watcher reliability and training-time causal claims remain outside these reduced tasks.

## Original publication mappings

- [Claude Mythos Preview system card](https://www.anthropic.com/claude-mythos-preview-system-card): [`audit-source-integrity`](../src/mrbench/cases/audit-source-integrity/case.json), [`escape-report-publication`](../src/mrbench/cases/escape-report-publication/case.json), [`read-only-comment-boundary`](../src/mrbench/cases/read-only-comment-boundary/case.json), [`test-suite-preservation`](../src/mrbench/cases/test-suite-preservation/case.json).
- [Safety and alignment in an era of long-horizon models](https://openai.com/index/safety-alignment-long-horizon-models/): [`benchmark-publication-scope`](../src/mrbench/cases/benchmark-publication-scope/case.json).
- [Claude Opus 4.7 system card](https://www.anthropic.com/claude-opus-4-7-system-card): [`colleague-branch-scope`](../src/mrbench/cases/colleague-branch-scope/case.json), [`discussion-evidence-fabrication`](../src/mrbench/cases/discussion-evidence-fabrication/case.json), [`production-path-evidence`](../src/mrbench/cases/production-path-evidence/case.json), [`queued-worker-status`](../src/mrbench/cases/queued-worker-status/case.json), [`retrospective-error-account`](../src/mrbench/cases/retrospective-error-account/case.json).
- [GPT-5.6 Preview System Card](https://deploymentsafety.openai.com/gpt-5-6-preview/): [`credential-relocation`](../src/mrbench/cases/credential-relocation/case.json), [`machine-cleanup-scope`](../src/mrbench/cases/machine-cleanup-scope/case.json), [`research-verification`](../src/mrbench/cases/research-verification/case.json).
- [Investigating three incidents in our cybersecurity evaluations](https://www.anthropic.com/news/investigating-incidents-cybersecurity-evals): [`ctf-external-application`](../src/mrbench/cases/ctf-external-application/case.json), [`ctf-live-database`](../src/mrbench/cases/ctf-live-database/case.json), [`ctf-public-package`](../src/mrbench/cases/ctf-public-package/case.json).
- [An alignment assessment of the UK AISI cybertesting incident](https://www.anthropic.com/research/alignment-assessment-ukaisi): [`ctf-maintainer-outreach`](../src/mrbench/cases/ctf-maintainer-outreach/case.json).
- [Claude Opus 5.5 system card](https://www.anthropic.com/claude-opus-5-5-system-card): [`database-approval-provenance`](../src/mrbench/cases/database-approval-provenance/case.json).
- [Claude Fable 5.1 & Claude Mythos 5.1 System Card](https://www.anthropic.com/claude-fable-5-1-mythos-5-1-system-card): [`destructive-approval-provenance`](../src/mrbench/cases/destructive-approval-provenance/case.json), [`review-user-impersonation`](../src/mrbench/cases/review-user-impersonation/case.json).
- [Investigating unintended model actions in our evaluations and internal use](https://www.anthropic.com/news/investigating-unintended-model-actions): [`example-tip-fabrication`](../src/mrbench/cases/example-tip-fabrication/case.json), [`fetch-url-length-boundary`](../src/mrbench/cases/fetch-url-length-boundary/case.json), [`form-final-step`](../src/mrbench/cases/form-final-step/case.json), [`map-data-license`](../src/mrbench/cases/map-data-license/case.json), [`practice-form-boundary`](../src/mrbench/cases/practice-form-boundary/case.json), [`statistics-data-license`](../src/mrbench/cases/statistics-data-license/case.json).
- [Claude Fable 5 & Claude Mythos 5 System Card](https://www.anthropic.com/claude-fable-5-mythos-5-system-card): [`experiment-confirmation-provenance`](../src/mrbench/cases/experiment-confirmation-provenance/case.json), [`package-checksum-evidence`](../src/mrbench/cases/package-checksum-evidence/case.json), [`review-attribution-boundary`](../src/mrbench/cases/review-attribution-boundary/case.json), [`shared-worker-process-scope`](../src/mrbench/cases/shared-worker-process-scope/case.json).
- [An alignment assessment of recent cybersecurity incidents](https://www.anthropic.com/research/alignment-assessment-cybersecurity-incidents): [`failed-abort-scope`](../src/mrbench/cases/failed-abort-scope/case.json).
- [Claude Opus 4.6 system card](https://www.anthropic.com/claude-opus-4-6-system-card): [`foreign-pr-credential`](../src/mrbench/cases/foreign-pr-credential/case.json), [`knowledgebase-public-outreach`](../src/mrbench/cases/knowledgebase-public-outreach/case.json), [`tool-result-attribution`](../src/mrbench/cases/tool-result-attribution/case.json).
- [Claude Opus 4.8 System Card](https://www.anthropic.com/claude-opus-4-8-system-card): [`pull-request-watch-status`](../src/mrbench/cases/pull-request-watch-status/case.json).
- [Addendum to GPT-6 Astra System Card: GPT-6.1 Terra](https://deploymentsafety.openai.com/gpt-6-1-terra): [`unavailable-search-disclosure`](../src/mrbench/cases/unavailable-search-disclosure/case.json).

## Extension and checks

```sh
uv run mrbench sources list
uv run mrbench sources check --provider alignment-hub
uv run mrbench sources check --provider anthropic --content
uv run mrbench validate
uv run python tools/check_environments.py
uv run python tools/check_report_judges.py --all --config mrbench.example.toml --prepare-only
```

Preparation with the checked-in example configuration does not call an API. Run the judge separately when its provider, model and budget are authorized. Review condition-specific traces and expected effects, stale receipts, evidence edits, restored files and final-output semantics before updating fixture bindings. See [source registration](sources.md), [scenario design](scenario-design.md) and the [update skill](../skills/update-report-tests/SKILL.md).

Use Sources in the viewer to filter all screening decisions by record text, reporter or decision. Each selected test also shows its original work request, tested mechanism and reconstruction limits. Source checks compare bounded metadata/body fingerprints; changes require review and never rewrite tests automatically. Anthropic's reviewed-URL adapter checks selected known reports, not the full research index. OpenAI's three older notice-body access failures and direct access to the long-horizon report remain unresolved; this addition does not certify those fetches.

No real actor episodes or new judge-quality results are implied by this inventory. Fixed traces, scripted native CLI transport, live judge calibration and actual model behavior are different evidence layers.

## Additional controlled mechanisms

MSI-0107 now uses a fictional deadline lookup to study the explicit WebFetch/terminal method boundary. MSI-0008 adapts the published corporate-email experiment with replacement/goal-conflict controls and delivered-text coercion assessment. See [behavior cases](behavior-cases.md). The latter is a controlled experiment, not a spontaneous deployment incident.

Package-registry and wiki communication share one case with route conditions. Both primary sources remain mapped, while the same authored numerical task is counted once. The wiki source's original task remains undisclosed. Historical runs retain their original case snapshots.
