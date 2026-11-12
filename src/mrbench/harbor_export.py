"""Generate Harbor tasks from the canonical benchmark case library."""

from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory

from . import __version__
from .catalog import digest, write_json
from .environment import implementation_source
from .harbor_bridge import MCP_URL, task_id
from .harnesses.base import toml_literal

RUNTIME_IMAGE = f"mrbench-harbor-runtime:{__version__}"
AGENT_IMAGE = f"mrbench-harbor-agent:{__version__}"


def task_config(case, sample, condition, name, runtime_image, timeout):
    return f'''schema_version = "1.4"
source = {toml_literal(case.spec['source']['url'])}
artifacts = [
  {{ source = "/mrbench-evidence", service = "simulation" }},
  {{ source = "/mrbench-actor", exclude = ["workspace"] }},
]

[task]
name = {toml_literal('misalign-report-bench/' + name)}
version = {toml_literal(case.spec['version'])}
description = {toml_literal(case.spec['title'])}

[metadata]
case_id = {toml_literal(case.id)}
sample_id = {toml_literal(sample['id'])}
sample_version = {toml_literal(sample['version'])}
condition_id = {toml_literal(condition['id'])}
reference_condition = {toml_literal(case.spec['default_condition'])}
framework_version = {toml_literal(__version__)}
case_hash = {toml_literal(digest(case.spec))}
sample_hash = {toml_literal(digest(sample))}

[agent]
timeout_sec = {timeout + 45}

[[environment.mcp_servers]]
name = "task"
transport = "streamable-http"
url = {toml_literal(MCP_URL)}

[verifier]
environment_mode = "separate"
timeout_sec = 90

[verifier.environment]
docker_image = {toml_literal(runtime_image)}
'''


def write_task(directory, case, sample, condition, runtime_image, agent_image, timeout, max_calls):
    name = directory.name
    world = case.environment(sample["id"], condition["id"])
    prompt = world.prompt
    first_line = prompt.partition("\n")[0].strip()
    if not first_line or "\r" in prompt or re.fullmatch(r"<!--.*canary.*-->|#.*canary.*", first_line, re.I):
        raise ValueError(f"Harbor would alter the instruction for {name}. Remove leading blanks, canaries or CR characters.")
    bundle = {
        "package_version": __version__, "environment_hash": digest(implementation_source(world)),
        "case": case.spec, "sample": sample, "condition": condition["id"], "max_calls": max_calls,
    }
    environment = directory / "environment"
    simulator = environment / "simulation"
    simulator.mkdir(parents=True)
    (directory / "task.toml").write_text(
        task_config(case, sample, condition, name, runtime_image, timeout), encoding="utf-8",
    )
    (directory / "instruction.md").write_text(prompt, encoding="utf-8")
    write_json(environment / "actor.json", {
        "input_hash": digest(bundle), "prompt_hash": digest(prompt), "policy": world.instructions,
        "tool_names": [tool["name"] for tool in world.tools], "timeout": timeout, "max_calls": max_calls,
    })
    (environment / "Dockerfile").write_text(
        f"FROM {agent_image}\nCOPY actor.json /mrbench-task/actor.json\n",
        encoding="utf-8",
    )
    (environment / ".dockerignore").write_text("*\n!Dockerfile\n!actor.json\n", encoding="utf-8")
    write_json(simulator / "bundle.json", bundle)
    (simulator / "Dockerfile").write_text(
        f"FROM {runtime_image}\nCOPY bundle.json /mrbench-task/bundle.json\n"
        'CMD ["python", "-m", "mrbench.harbor_bridge", "serve"]\n',
        encoding="utf-8",
    )
    (environment / "docker-compose.yaml").write_text('''services:
  main:
    depends_on:
      simulation:
        condition: service_healthy
  simulation:
    build: ./simulation
    healthcheck:
      test: ["CMD", "python", "-c", "import socket; socket.create_connection(('127.0.0.1', 8000), 2).close()"]
      interval: 1s
      timeout: 3s
      retries: 30
''', encoding="utf-8")



def export(cases, output, *, runtime_image=RUNTIME_IMAGE, agent_image=AGENT_IMAGE, timeout=180, max_calls=40):
    if any(not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_./:@-]*", image) for image in (runtime_image, agent_image)):
        raise ValueError("Use valid Docker image references")
    output = output.resolve()
    if output.exists():
        raise ValueError("Export requires a new output directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with TemporaryDirectory(dir=output.parent, prefix=".mrbench-export-") as temporary:
        staging = Path(temporary) / "dataset"
        for case in sorted(cases, key=lambda case: case.id):
            for sample in case.samples.values():
                for condition in case.spec["conditions"]:
                    name = task_id(case.id, sample["id"], condition["id"])
                    group = "main" if condition["id"] == case.spec["default_condition"] else "controls"
                    directory = staging / group / name
                    write_task(directory, case, sample, condition, runtime_image, agent_image, timeout, max_calls)
                    rows.append({"path": f"{group}/{name}", "case": case.id, "sample": sample["id"], "condition": condition["id"]})
        if not rows:
            raise ValueError("No cases selected for export")
        shutil.copyfile(Path(__file__).with_name("harbor_metric.py"), staging / "metric.py")
        for group in ("main", "controls"):
            if (staging / group).is_dir():
                write_json(staging / f"{group}.job.json", {
                    "datasets": [{"path": group}],
                    "metrics": [{"type": "uv-script", "kwargs": {"script_path": "metric.py"}}],
                })
        write_json(staging / "manifest.json", {"framework_version": __version__, "tasks": rows})
        staging.rename(output)
    return rows
