"""Optional Harbor adapter for the benchmark's native reference profiles."""

import shlex

from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.installed.base import NonZeroAgentExitCodeError

from . import __version__
from .harbor_bridge import MCP_URL


class ReferenceAgent(BaseAgent):
    capabilities = AgentCapabilities(mcp_servers=True)

    def __init__(self, *args, harness="codex", effort="medium", trial=1, **kwargs):
        super().__init__(*args, **kwargs)
        self.harness = harness
        self.effort = effort
        self.trial = trial

    @staticmethod
    def name():
        return "mrbench-reference"

    def version(self):
        return __version__

    async def setup(self, environment):
        if [(server.name, server.transport, server.url) for server in self.mcp_servers] != [
            ("task", "streamable-http", MCP_URL),
        ]:
            raise ValueError("Expected the exported task simulator as the only MCP server")
        if self.harness not in {"codex", "grok"} or self.effort not in {"low", "medium", "high"}:
            raise ValueError("Unknown reference harness or reasoning effort")
        if not self.model_name:
            raise ValueError("Select a model with Harbor --model")

    async def run(self, instruction, environment, context):
        command = shlex.join([
            "python", "-m", "mrbench.harbor_bridge", "actor",
            "--harness", self.harness, "--effort", self.effort, "--trial", str(self.trial),
            "--model", self.model_name.split("/", 1)[-1], "--instruction=" + instruction,
        ])
        allowed = {"OPENAI_API_KEY", "CODEX_API_KEY", "XAI_API_KEY", "MRBENCH_ACTOR_BASE_URL",
                   "MRBENCH_ACTOR_API_KEY", "MRBENCH_PROTOCOL_CHECK"}
        env = {name: value for name, value in self._extra_env.items() if name in allowed}
        result = await environment.exec(command, env=env)
        if result.return_code:
            raise NonZeroAgentExitCodeError(result.stderr or result.stdout or "Reference adapter failed")
