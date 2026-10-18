"""Standard stdio MCP transport over the same independently usable Environment."""

import asyncio
import json
from pathlib import Path

from .catalog import Case, read_json, write_json
from .catalog import digest
from .environment import implementation_source
from .evidence import verify_input_hashes


async def serve(run_dir: Path):
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import CallToolResult, TextContent, Tool

    manifest = read_json(run_dir / "run.json")
    verify_input_hashes(manifest, run_dir)
    if manifest.get("status") != "running":
        raise ValueError("MCP requires a fresh running episode")
    if (run_dir / "events.jsonl").exists() and (
        run_dir / "events.jsonl"
    ).stat().st_size:
        raise ValueError(
            "An MCP world with recorded actions cannot be restarted; create a new run"
        )
    case = Case(
        run_dir, manifest["case"], {manifest["sample"]["id"]: manifest["sample"]}
    )
    environment = case.environment(
        manifest["sample"]["id"], manifest["condition"]["id"]
    )
    if digest(implementation_source(environment)) != manifest["hashes"]["environment"]:
        raise ValueError("MCP environment differs from its recorded implementation")
    environment.max_calls = manifest["config"]["max_calls"]
    environment.persist(run_dir)
    server = Server("task-tools")

    @server.list_tools()
    async def list_tools():
        write_json(
            run_dir / "mcp-ready.json",
            {
                "server": "misalign-report-bench",
                "tools": [t["name"] for t in environment.tools],
            },
        )
        return [Tool(**t) for t in environment.tools]

    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict):
        try:
            result = environment.call(name, arguments or {})
        except RuntimeError:
            write_json(
                run_dir / "budget-exhausted.json", {"max_calls": environment.max_calls}
            )
            raise
        finally:
            environment.persist(run_dir)
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(result, ensure_ascii=False))
            ],
            isError=bool(result.get("error") and "status" not in result),
        )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


def main(run_dir: Path):
    asyncio.run(serve(run_dir.resolve()))
