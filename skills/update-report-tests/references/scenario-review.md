# Scenario review

Read this when changing a task, environment, control, final deliverable or rubric. The maintained [scenario guide](../../../docs/scenario-design.md) records current per-case scope; this reference highlights decisions that can silently invalidate an update.

## Reconstruct the causal path

Before implementing, make a short local adaptation record:

- Public source and exact selected component, including any technical supplement and evidence uncertainty.
- Legitimate user task and requested deliverable. Distinguish disclosed task text from a reconstruction.
- Missing information, tool constraint or other obstacle that makes the unwanted action relevant.
- Available normal interfaces, trusted authorization policy, and lower-trust source/attack material.
- The observable action or output that would demonstrate the selected threat, plus a compliant route or honest incomplete outcome.
- What is preserved, invented, reduced and omitted; what the experiment cannot conclude.

Put stable source/scope explanations in `source`, `abstraction` and `scenario_review`, with component mappings in the provider snapshot. Keep execution diaries and review working notes local. Use `decision-rehearsal` or `mechanism-study` according to the actual reduction, not a desired fidelity claim.

## Inspect the actual actor surface

Use `tools/review_scenarios.py` to inspect task text, trusted instructions, tool schemas and available authored lower-trust material. Trace ordinary reads/searches that expose relevant capabilities; the exporter alone cannot inspect every dynamic tool response or establish fidelity.

| Risk | Required review |
| --- | --- |
| Turning a spontaneous failure into obedience | Preserve the ordinary work request. Do not add a request to upload, evade a restriction, post to another task or conceal errors unless that is actually the source-authorized task. The lake task asks for results and their data/filter basis; browser citations and upload are not task requirements. |
| Removing a source-authentic attack | Preserve deliberate email, Slack, webpage or file injection in its lower-trust surface. Keep the user task and developer/tool policy separate from attacker content. |
| Confusing summary production with consumption | A producer starts with legitimate work and a checkpoint transition, not the unwanted summary already supplied. A consumer may receive a contaminated prior summary as source material. Staged checkpoints do not reproduce native compaction. |
| Giving away the route or answer | Normal tool documentation may describe ordinary capabilities and discoverable service URLs. It must not supply an exploit recipe, hidden file-read command, expected flag, private result or benchmark-only marker as a task hint. Review tool names, help, errors and condition overrides as well as prompts. |
| Making discovery artificial | Relevant queries and normal documentation reads should reveal plausible interfaces. Do not make every unrelated query return every workaround service. Preserve the normal route needed to complete available-data controls. |
| Erasing normal data in a clean control | Remove only the attack-bearing content. Retain the actual dataset, bibliography, files, channel and ordinary tool access. `condition.files` overlays apply before family setup; inspect the resulting world, not just the JSON edit. |
| Changing expectations without changing availability | An available-data control must return readable evidence through its tools. Update its static judge facts consistently; do not call an unreadable source available merely by changing the rubric. |
| Manufacturing an authorization violation | Preserve explicit permission and the source's actual scope. Ordinary public reading of another host is not automatically compromise. Opening a form is not submitting an account. Additional experimental restrictions must be named as adaptations and compared separately. |
| Inferring success from a response string | Separate attempted actions, committed effects and authorization. Inspect events and persistent state; HTTP success text, redirects or errors alone do not settle whether a write, account, read or upload occurred. Cleanup of one object may leave other changes intact. |
| Replacing requested work with an easy status task | An honest missing-input explanation can avoid fabrication while leaving the original numerical, research, coding or deployment task incomplete. A task that actually asks for a status/checkpoint has different completion criteria. Preserve the source work goal when adding a handoff transition. |
| Hiding requirements inside grading | Derive completion criteria from the task. Keep measurable diagnostics separate from requirements: lake citation coverage is measured even though citations are optional; limitation disclosure is inapplicable there. Preserve references when a task requires them. Check voluntary verification claims against known source capabilities. |
| Accepting chat while the artifact is wrong | Judge the actual saved email, inbox, file, script or handoff through declared final-output selectors. Require necessary state transitions/checks separately. Missing or whitespace-only required text cannot establish completion. |
| Equating answer quality with action compliance | A correct deliverable can coexist with an unauthorized action; an honest blocker can coexist with incomplete work. Do not derive answer labels from the fixture's `safe`/`unsafe` trace name or send the action verdict to the judge. |
| Relabelling source uncertainty | Preserve legitimate behavior, unverified allegations, uncertain AI attribution and the source's observation limits. A probe or 4xx response does not prove successful exploitation. Do not turn source-requested booking/account actions into unauthorized behavior. |

## Keep reduced mechanisms explicit

The three Hugging Face-derived cases retain the designated local sandbox exercise and an independent scope boundary. The checker validates the in-scope marker join captured at setup; editing the manifest must not redefine success. Preserve the authorized target, ordinary discovery of external routes, and separate scope-attempt/commitment scoring. This local exercise does not reproduce the original security task's difficulty or incentives. A new substantial simplification requires review of that lost causal structure.

Likewise, finite reference mappings are not general hidden-test implementations; a bounded JavaScript recognizer is not a browser/runtime; algebraic checks are not Lean; a scripted checkpoint is not native compaction. Preserve the limitation and test supported/unsupported paths honestly. Never execute source-contained payloads on the host to make a simulation appear realistic.

Choose controls that isolate the selected variable: permission, actual evidence availability, attack presence or enforcement. A control should retain a meaningful normal task. For each changed control, inspect task wording, trusted policy, tool definitions, returned content, world state and judge context together.

If the public report omits crucial instructions, read the supporting material and label reconstruction explicitly. If a faithful test is still unsupported, defer that component or discuss the tradeoff; do not hide the gap behind green tests or an incident-count increase.
