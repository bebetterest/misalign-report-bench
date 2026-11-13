# Run MisalignReportBench with Harbor

Harbor is the recommended runner for benchmark evaluations. The checked-in [snapshot](../harbor-tasks/) contains a task directory for each case, sample and condition, split into `main/` for default conditions and `controls/` for controlled changes. Each task is one episode and can take multiple tool calls. The [manifest](../harbor-tasks/manifest.json) maps task directories to their original IDs.

## Prepare the images

Use [Harbor 0.25.0](https://github.com/harbor-framework/harbor/releases/tag/v0.25.0), Python 3.12 and Docker with Compose. Build both images from the checkout containing the snapshot you plan to run. Put the Linux CLI binaries for your container architecture in the build directory: `codex` and its matching `codex-code-mode-host` (and `bwrap` if supplied by that release), or `grok` for Grok Build. On Apple Silicon, use the Linux ARM64 binaries. See the [Codex releases](https://github.com/openai/codex/releases) and [Grok Build CLI setup](https://docs.x.ai/build/cli/installation).

```sh
build_dir=$(mktemp -d)
version=$(uv run python -c 'from mrbench import __version__; print(__version__)')
uv build --wheel --out-dir "$build_dir"
uv export --locked --no-dev --no-emit-project --format requirements-txt \
  --output-file "$build_dir/requirements.txt"
mkdir "$build_dir/bin"
# Install the downloaded Linux binaries into "$build_dir/bin" with mode 755.
docker build -f harbor/Dockerfile --target runtime -t "mrbench-harbor-runtime:$version" "$build_dir"
docker build -f harbor/Dockerfile --target agent -t "mrbench-harbor-agent:$version" "$build_dir"
```

The runtime image runs the simulator and verifier. The agent image adds the CLI binaries and removes the bundled case data. Use `--runtime-image` and `--agent-image` when publishing these images to a registry or when testing different pinned builds. The task directory contains the selected inputs. Harbor starts the simulator alongside the agent as a separate service and starts a separate verifier to score the collected evidence. [Harbor Compose environments](https://docs.harborframework.com/tasks/multi-container)

## Run the snapshot

From the repository root, enter the dataset directory so the job config can find its dataset and shared metric.

```sh
cd harbor-tasks
uv run --locked --project .. --python 3.12 --with harbor==0.25.0 harbor run \
  -c main.job.json -p main -i citation-upload__lakes-001__blocked-unapproved \
  -a mrbench.harbor_agent:ReferenceAgent -m openai/YOUR_MODEL \
  --ae 'OPENAI_API_KEY=${OPENAI_API_KEY}' -o ../runs/harbor
```

Omit `-p main -i ...` to run every main task. For controls, use `-c controls.job.json` and, to select individual tasks, `-p controls -i TASK_DIRECTORY_NAME`. Keep `-o ../runs/harbor` to store results in the repository's ignored runs directory. For Grok Build, install its Linux binary in the agent image, pass `--ak harness=grok`, use `-m xai/YOUR_MODEL` and replace the actor credential flag with `--ae 'XAI_API_KEY=${XAI_API_KEY}'`.

The reference adapter runs the same Codex or Grok profile as the Python CLI. It supplies the tool policy separately from `instruction.md`. To use a different Harbor agent with the reference verifier, implement an adapter that preserves the task's MCP and instruction boundary and emits the expected final answer and execution record.

## Score the answer

To score the answer as well as tool actions, pass these verifier settings. Supply the actual key in your environment. The value `${MRBENCH_JUDGE_API_KEY}` is resolved by Harbor for the verifier phase.

```sh
--ve 'MRBENCH_JUDGE_API_KEY=${MRBENCH_JUDGE_API_KEY}' \
--ve 'MRBENCH_JUDGE_MODEL=YOUR_JUDGE_MODEL' \
--ve 'MRBENCH_JUDGE_BASE_URL=https://api.openai.com/v1'
```

Custom actor endpoints can use `--ae 'MRBENCH_ACTOR_BASE_URL=https://your-endpoint.example/v1'` and `--ae 'MRBENCH_ACTOR_API_KEY=${MRBENCH_ACTOR_API_KEY}'`. The Codex override uses Responses and the Grok override uses Chat Completions. Set the URL to the service's API base. The judge remains a separate Chat Completions call with the final answer and declared final task texts. When no judge model is set, action scoring still runs and the answer score stays pending. A configured judge with missing credentials or invalid settings records an answer scoring error and preserves valid action scores.

## Inspect the results

The simulator records events and state in its own container. The actor checks the exported input with that simulator before starting, and the verifier checks that both artifacts belong to the same episode. Harbor copies the evidence and native actor output into the separate verifier. The verifier writes the original `mrbench` record under each trial's `verifier/record/` and emits numeric Harbor metrics for scored outcomes. Both generated job configs use the shared `metric.py`, which uses the scored denominator for each rate. The tool violation rate uses valid completed trials. The metric separately totals `incomplete_violation_attempts` and `incomplete_violations` from verified evidence in incomplete trials. Use those configs for aggregates. Cases with objective task effects also report `task_effects_complete`. For the shared booking case, `booking_request_honored` covers valid runs, while `confirmed_before_message_review` covers runs with a confirmed booking. A bare `harbor run -p ...` still produces the raw record, but Harbor 0.25.0 uses its default mean without the job config.

To view a record in `mrbench view`, copy `verifier/record/` to a directory under your runs root using its `run.json` ID as the directory name. The viewer retains the same final answer, evidence, and scoring breakdown. The `harbor` backend is part of the recorded configuration for comparisons. Re-score against the same evidence through `mrbench score` or Harbor's separate-verifier regrade workflow.

For `paired-safety-underperformance`, use one Harbor attempt per arm with the same explicit `--ak trial=N`. Assign a distinct number to each repeated pair, and alternate which arm goes first if controlling for order. Copy the records to a dedicated runs directory and use `tools/compare_paired.py`. Its default input is real model runs. The `--protocol-check` option supports comparing scripted verification records separately.


## Regenerate the snapshot

The Python case library is the source of truth. After editing cases or changing the exporter, regenerate the tasks and review the generated diff before committing. The exporter requires a new output directory. From the repository root:

```sh
snapshot_dir=$(mktemp -d)
uv run mrbench export-harbor --output "$snapshot_dir/harbor-tasks"
diff -ru harbor-tasks "$snapshot_dir/harbor-tasks"
```

For an intentional update, replace the tracked `harbor-tasks/` tree with the newly generated tree. Rebuild the Docker images from the updated checkout when the runtime changes. CI regenerates the full snapshot and checks it against the tracked copy.

For a separate export, repeat `--case` to select specific cases, use `--cases` for an editable library or set `--runtime-image` and `--agent-image` for custom image tags. For example, `uv run mrbench export-harbor --case citation-upload --output .cache/harbor-lakes` exports the three lake conditions. The exporter rejects leading blanks or canary lines that Harbor would strip from an instruction.
