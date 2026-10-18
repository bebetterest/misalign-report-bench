"""Read-only loopback viewer. No browser route can launch a model or modify a run."""

from copy import deepcopy
from datetime import datetime
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import mimetypes
from pathlib import Path
import re
import shlex
from urllib.parse import unquote, urlsplit
import zipfile

from .catalog import BUILTIN_CASES, digest, read_json
from .evidence import (
    load_action_evidence,
    task_completion,
    verify_answer_score,
    verify_input_hashes,
)
from .source_registry import SOURCE_INDEX

WEB = Path(__file__).parent / "web"
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


def run_directory(root, run_id):
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run id")
    path = (root / run_id).resolve()
    if (
        (root / run_id).is_symlink()
        or path.parent != root.resolve()
        or not (path / "run.json").is_file()
        or (path / "run.json").is_symlink()
    ):
        raise ValueError("Run not found")
    return path


def local_json(path):
    if path.is_symlink():
        raise ValueError("Linked artifacts are not served")
    return read_json(path)


def read_record(path):
    manifest = local_json(path / "run.json")
    scores = local_json(path / "scores.json") if (path / "scores.json").exists() else {}
    if not isinstance(manifest, dict) or not isinstance(scores, dict):
        raise ValueError("Run records must be objects")
    digest([manifest, scores])  # Reject non-finite JSON before serving it to a browser.
    for section, fields in (
        ("case", ("id", "title", "version")),
        ("sample", ("id", "title", "version")),
        ("condition", ("id", "title")),
        ("config", ("model",)),
        ("hashes", ("case", "sample", "environment", "config")),
    ):
        value = manifest.get(section)
        if not isinstance(value, dict) or any(
            not isinstance(value.get(key), str) or not value[key] for key in fields
        ):
            raise ValueError(f"Invalid run {section}")
    for key in ("origin", "status", "created_at"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise ValueError(f"Missing run {key}")
    datetime.fromisoformat(manifest["created_at"])
    for section in ("actions", "answer"):
        if section in scores and not isinstance(scores[section], dict):
            raise ValueError("Invalid score structure")
    actions, answer = scores.get("actions", {}), scores.get("answer", {})
    if actions.get("status") in ("scored", "observed_in_incomplete_run") and any(
        not isinstance(actions.get(key), bool)
        for key in ("violation_observed", "violation_attempted")
    ):
        raise ValueError("Scored actions require boolean violation flags")
    if answer.get("status") == "scored" and not isinstance(
        answer.get("task_completed"), bool
    ):
        raise ValueError("Scored answers require boolean task completion")
    not_applicable = answer.get("not_applicable_fields", [])
    if not isinstance(not_applicable, list) or any(
        not isinstance(key, str) for key in not_applicable
    ):
        raise ValueError("Inapplicable answer fields must be a list of names")
    if "evaluation" in answer:
        if not isinstance(answer["evaluation"], dict):
            raise ValueError("Answer evaluation must be an object")
        for key, item in answer["evaluation"].items():
            if key == "confidence":
                if item not in ("high", "medium", "low"):
                    raise ValueError("Invalid judge confidence")
                continue
            if (
                not isinstance(item, dict)
                or item.get("value") is not None
                and not isinstance(item["value"], bool)
                or not isinstance(item.get("reason"), str)
                or not isinstance(item.get("evidence"), str)
            ):
                raise ValueError("Invalid answer criterion")
    return manifest, scores


def display_scores(path, manifest, scores):
    """Mask stale grades in memory; the viewer never rewrites historical evidence."""
    scores = deepcopy(scores)
    warnings = []
    actions = scores.get("actions", {})
    if actions.get("status") in ("scored", "observed_in_incomplete_run"):
        try:
            verify_input_hashes(manifest, path)
            _, _, hashes = load_action_evidence(path)
            if "evidence_hashes" in actions and actions["evidence_hashes"] != hashes:
                raise ValueError(
                    "Stored action grade belongs to different event/state evidence"
                )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            actions.update(
                status="unscored",
                violation_observed=None,
                violation_attempted=None,
                error=str(exc),
            )
            warnings.append("Action evidence: " + str(exc))
    answer = scores.get("answer", {})
    try:
        verify_answer_score(path, manifest, answer)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        answer.update(status="needs_review", task_completed=None, error=str(exc))
        warnings.append("Answer evidence: " + str(exc))
    completed = (
        task_completion(answer, actions, manifest.get("task_effects_required", False))
        if manifest["status"] == "completed"
        else None
    )
    scores["task_completed"] = completed
    scores["compliant_task_completed"] = (
        completed and not actions["violation_attempted"]
        if answer.get("status") == "scored"
        and actions.get("status") == "scored"
        and manifest["status"] == "completed"
        else None
    )
    return scores, warnings


def list_runs(root):
    records, warnings = [], []
    if root.is_dir():
        for path in sorted(root.iterdir(), reverse=True):
            if path.is_dir() and (path / "run.json").is_file():
                try:
                    run_directory(root, path.name)
                    manifest, stored = read_record(path)
                    scores, integrity_warnings = display_scores(path, manifest, stored)
                    manifest.update(
                        scores=scores,
                        id=path.name,
                        integrity_warnings=integrity_warnings,
                    )
                    records.append(manifest)
                    warnings.extend(
                        f"Run {path.name}: {message}" for message in integrity_warnings
                    )
                except (OSError, ValueError, KeyError, TypeError):
                    warnings.append(f"Could not read run {path.name}")
    return records, warnings


def compatible_groups(records):
    groups = {}
    for record in records:
        if record.get("origin") != "codex" or record.get("status") != "completed":
            continue
        scores = record.get("scores", {})
        actions = scores.get("actions", {})
        if actions.get("status") != "scored" or any(
            not isinstance(actions.get(key), bool)
            for key in ("violation_observed", "violation_attempted")
        ):
            continue
        hashes = record["hashes"]
        key = digest(
            {
                "case": hashes["case"],
                "sample": hashes["sample"],
                "environment": hashes["environment"],
                "framework": hashes.get("framework", "legacy"),
                "config": hashes.get("comparison_config", hashes["config"]),
                "answer_judge": scores.get("answer", {}).get("config_hash"),
                "judge_response_model": scores.get("answer", {}).get("response_model"),
                "judge_fingerprint": scores.get("answer", {}).get("system_fingerprint"),
                "scorer": scores.get("scorer_hash", "legacy"),
            }
        )
        group = groups.setdefault(
            key,
            {
                "id": key,
                "case_id": record["case"]["id"],
                "sample_id": record["sample"]["id"],
                "model": record["config"]["model"],
                "case_version": record["case"]["version"],
                "sample_version": record["sample"]["version"],
                "conditions": {},
            },
        )
        condition = group["conditions"].setdefault(
            record["condition"]["id"],
            {
                "runs": 0,
                "violations": 0,
                "violation_attempts": 0,
                "answer_scored": 0,
                "task_scored": 0,
                "task_completed": 0,
            },
        )
        condition["runs"] += 1
        condition["violations"] += int(
            scores["actions"].get(
                "violation_observed",
                scores["actions"].get("unauthorized_upload", False),
            )
        )
        condition["violation_attempts"] += int(
            scores["actions"].get(
                "violation_attempted",
                scores["actions"].get("unauthorized_attempt", False),
            )
        )
        if scores.get("answer", {}).get("status") == "scored" and isinstance(
            scores["answer"].get("task_completed"), bool
        ):
            condition["answer_scored"] += 1
        completed = task_completion(
            scores.get("answer", {}),
            actions,
            record.get("task_effects_required", False),
        )
        if type(completed) is bool:
            condition["task_scored"] += 1
            condition["task_completed"] += int(completed)
    return list(groups.values())


def reproduction(manifest):
    if manifest["origin"] == "demo":
        command = ["uv", "run", "mrbench", "demo"]
        if manifest.get("case_library"):
            command.extend(["--cases", manifest["case_library"]])
        return shlex.join(command)
    if manifest["origin"] == "codex-smoke":
        command = [
            "uv",
            "run",
            "python",
            "tools/smoke_codex.py",
            "--case",
            manifest["case"]["id"],
            "--condition",
            manifest["condition"]["id"],
        ]
        if "protocol_trace" in manifest:
            command.extend(["--trace", manifest["protocol_trace"]])
        if manifest["config"].get("codex_executable"):
            command.extend(["--codex", manifest["config"]["codex_executable"]])
        return shlex.join(command)
    if manifest["origin"] == "judge-check":
        return "uv run python tools/check_judge.py --config mrbench.toml"
    if manifest["origin"] == "environment-check":
        return shlex.join(
            [
                "uv",
                "run",
                "python",
                "tools/check_environments.py",
                "--case",
                manifest["case"]["id"],
                "--condition",
                manifest["condition"]["id"],
                "--trace",
                manifest["config"]["trace"],
            ]
        )
    command = [
        "uv",
        "run",
        "mrbench",
        "run",
        manifest["case"]["id"],
        "--sample",
        manifest["sample"]["id"],
        "--condition",
        manifest["condition"]["id"],
        "--model",
        manifest["config"]["model"],
        "--effort",
        manifest["config"]["effort"],
        "--timeout",
        str(manifest["config"]["timeout"]),
        "--max-calls",
        str(manifest["config"]["max_calls"]),
    ]
    if manifest.get("case_library"):
        command.extend(["--cases", manifest["case_library"]])
    if manifest["config"].get("codex_executable"):
        command.extend(["--codex", manifest["config"]["codex_executable"]])
    return shlex.join(command)


def text_file(path, limit=2_000_000):
    if path.is_symlink():
        raise ValueError("Linked artifacts are not served")
    if not path.is_file():
        return {"text": "", "truncated": False}
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    return {
        "text": data[:limit].decode("utf-8", errors="replace"),
        "truncated": len(data) > limit,
    }


def details(root, run_id):
    path = run_directory(root, run_id)
    manifest, stored = read_record(path)
    scores, warnings = display_scores(path, manifest, stored)
    task_outputs = None
    if (path / "task-outputs.json").exists():
        try:
            from .evidence import validate_task_outputs

            task_outputs = local_json(path / "task-outputs.json")
            context = local_json(path / "judge-context.json")
            validate_task_outputs(task_outputs, context.get("output_requirements", []))
        except (OSError, ValueError, TypeError, KeyError):
            task_outputs = None
            warnings.append(
                "Final task texts could not be read; export the original evidence for review."
            )
    return {
        "manifest": manifest,
        "scores": scores,
        "integrity_warnings": warnings,
        "task": text_file(path / "prompt.txt"),
        "answer": text_file(path / "answer.txt"),
        "task_outputs": task_outputs,
        "events": text_file(path / "events.jsonl"),
        "codex": text_file(path / "codex.jsonl"),
        "state": local_json(path / "state.json")
        if (path / "state.json").exists()
        else None,
        "reproduction": reproduction(manifest),
        "score_command": shlex.join(
            [
                "uv",
                "run",
                "mrbench",
                "score",
                run_id,
                "--runs",
                str(root.resolve()),
                "--judge",
                "--config",
                "mrbench.toml",
            ]
        ),
    }


def sample_reproduction(case, sample_id):
    command = [
        "uv",
        "run",
        "mrbench",
        "run",
        case.id,
        "--sample",
        sample_id,
        "--model",
        "YOUR_CODEX_MODEL",
    ]
    if case.path.parent != BUILTIN_CASES.resolve():
        command.extend(["--cases", str(case.path.parent)])
    return shlex.join(command)


def export_run(root, run_id):
    path = run_directory(root, run_id)
    buffer = io.BytesIO()
    allowed = [
        "run.json",
        "prompt.txt",
        "command.json",
        "judge-context.json",
        "task-outputs.json",
        "answer.txt",
        "events.jsonl",
        "state.json",
        "scores.json",
        "codex.jsonl",
        "codex.stderr.log",
        "mcp-ready.json",
        "budget-exhausted.json",
        "protocol-check.json",
        "model-catalog.json",
    ]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in allowed:
            file = path / name
            if file.is_file() and not file.is_symlink():
                archive.write(file, name)
        for folder in ("grading", "score-history", "validation-history"):
            for file in (path / folder).glob("**/*.json"):
                if not file.is_symlink() and file.resolve().is_relative_to(path):
                    archive.write(file, str(file.relative_to(path)))
    return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, cases, root, sources=None, **kwargs):
        self.cases = cases
        self.root = root.resolve()
        self.sources = sources or SOURCE_INDEX
        super().__init__(*args, **kwargs)

    def log_message(self, *args):
        pass

    def send_data(self, data, content_type, status=200, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
        )
        if filename:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, value, status=200):
        self.send_data(
            json.dumps(value, ensure_ascii=False).encode(),
            "application/json; charset=utf-8",
            status,
        )

    def do_GET(self):
        if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            return self.send_json({"error": "Loopback host required"}, 403)
        path = unquote(urlsplit(self.path).path)
        try:
            if path == "/api/sources":
                from .coverage import source_coverage

                return self.send_json(source_coverage(self.cases, self.sources))
            if path == "/api/catalog":
                return self.send_json(
                    [
                        {
                            **case.spec,
                            "samples": list(case.samples.values()),
                            "reproduction_commands": {
                                sid: sample_reproduction(case, sid)
                                for sid in case.samples
                            },
                            "tools": case.environment(
                                case.spec["default_sample"],
                                case.spec["default_condition"],
                            ).tools,
                        }
                        for case in self.cases.values()
                    ]
                )
            if path == "/api/runs":
                records, warnings = list_runs(self.root)
                return self.send_json(
                    {
                        "runs": records,
                        "warnings": warnings,
                        "groups": compatible_groups(records),
                    }
                )
            match = re.fullmatch(r"/api/runs/([^/]+)(/export)?", path)
            if match:
                if match[2]:
                    return self.send_data(
                        export_run(self.root, match[1]),
                        "application/zip",
                        filename=match[1] + ".zip",
                    )
                return self.send_json(details(self.root, match[1]))
            if path in ("/", "/index.html"):
                file = WEB / "index.html"
            elif path.startswith("/assets/"):
                file = (WEB / path.removeprefix("/assets/")).resolve()
                if not file.is_relative_to(WEB.resolve()):
                    raise ValueError("Invalid asset path")
            else:
                raise ValueError("Not found")
            if not file.is_file():
                raise ValueError("Not found")
            return self.send_data(
                file.read_bytes(),
                mimetypes.guess_type(file.name)[0] or "application/octet-stream",
            )
        except (OSError, ValueError, KeyError, TypeError):
            return self.send_json({"error": "Record or asset unavailable"}, 404)


def make_server(cases, root, port=0, *, sources=None):
    return ThreadingHTTPServer(
        ("127.0.0.1", port), partial(Handler, cases=cases, root=root, sources=sources)
    )


def serve(cases, root, port, *, sources=None):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    server = make_server(cases, root, port, sources=sources)
    print(
        f"MisalignReportBench → http://127.0.0.1:{server.server_port} (read-only)",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
