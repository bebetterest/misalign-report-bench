"""The existing closed Codex reference profile behind the harness contract."""

from .. import codex
from ..catalog import write_json
from .base import HarnessInfo, HarnessResult


class CodexHarness:
    id = "codex"
    evidence_modules = (
        "mrbench.harnesses.codex", "mrbench.harnesses.base", "mrbench.codex",
    )

    def preflight(self, config):
        if config.options:
            raise ValueError("Codex harness options only support executable")
        native = codex.capabilities(codex.resolve_codex(config.executable))
        artifacts = {}
        catalog_info = None
        if config.model:
            catalog, catalog_info = codex.reference_catalog(native, config.model)
            artifacts["model-catalog.json"] = catalog
        if config.provider_config:
            if set(config.provider_config) - {"model_provider", "model_providers"}:
                raise ValueError("Invalid programmatic Codex provider override")
            native["provider_config"] = config.provider_config
        settings = {
            "codex_version": native["version"],
            "codex_executable": native["executable"],
            "code_mode_host": native.get("code_mode_host"),
            "model_catalog": catalog_info,
            "disabled_features": sorted(codex.DISABLED_FEATURES.intersection(native["features"])),
            "context_guard": native["context_guard"],
            "provider_config": config.provider_config,
        }
        return HarnessInfo(
            self.id, native["version"], codex.PROFILE_VERSION, native["executable"],
            settings, artifacts, {"native": native, "use_auth": config.use_auth},
        )

    def run(self, episode):
        args = codex.command(
            episode.info.runtime["native"], episode.model, episode.workspace,
            episode.run_dir / "answer.txt", run_dir=episode.run_dir,
            effort=episode.effort, task_instructions=episode.instructions,
        )
        write_json(episode.run_dir / "command.json", {"argv": args})
        execution = codex.execute(
            args, episode.prompt, episode.workspace, episode.run_dir / "codex",
            episode.timeout, code_mode_host=episode.info.settings.get("code_mode_host"),
            use_auth=episode.info.runtime.get("use_auth", True),
        )
        return HarnessResult(
            execution, codex.inspect_stream(episode.run_dir / "codex.jsonl", allow_mcp=True),
        )
