import asyncio
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mrbench.catalog import catalog, read_json
from mrbench.runs import prepare


class MCPTests(unittest.TestCase):
    def test_every_new_default_case_runs_through_the_real_stdio_transport(self):
        fixtures = read_json(Path(__file__).parent / "fixtures/report-scenarios.json")[
            "fixtures"
        ]
        cases = catalog()

        async def scenario(root):
            for cid, fixture in fixtures.items():
                with self.subTest(case=cid):
                    case = cases[cid]
                    path, _, _ = prepare(
                        case,
                        fixture["sample"],
                        "main",
                        root,
                        {"max_calls": 40, "model": "stdio-fixture"},
                        "demo",
                    )
                    parameters = StdioServerParameters(
                        command=sys.executable,
                        args=["-m", "mrbench", "mcp", "--run-dir", str(path)],
                    )
                    async with stdio_client(parameters) as (reader, writer):
                        async with ClientSession(
                            reader, writer, read_timeout_seconds=timedelta(seconds=15)
                        ) as session:
                            await session.initialize()
                            definitions = await session.list_tools()
                            expected = case.environment(fixture["sample"], "main")
                            self.assertEqual(
                                {t.name for t in definitions.tools},
                                {t["name"] for t in expected.tools},
                            )
                            for call in fixture["unsafe"]:
                                result = await session.call_tool(
                                    call["tool"], call["arguments"]
                                )
                                expected_result = expected.call(
                                    call["tool"], call["arguments"]
                                )
                                self.assertEqual(
                                    result.isError,
                                    bool(
                                        expected_result.get("error")
                                        and "status" not in expected_result
                                    ),
                                )
                                self.assertEqual(
                                    json.loads(result.content[0].text), expected_result
                                )
                    state = read_json(path / "state.json")
                    self.assertEqual(state["world"], expected.snapshot())
                    self.assertEqual(state["event_count"], len(fixture["unsafe"]))
                    self.assertTrue((path / "mcp-ready.json").exists())

        with tempfile.TemporaryDirectory() as root:
            asyncio.run(scenario(Path(root)))

    def test_real_stdio_handshake_tools_upload_and_persistence(self):
        async def scenario(path):
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "mrbench", "mcp", "--run-dir", str(path)],
            )
            async with stdio_client(parameters) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual(
                        {t.name for t in tools.tools},
                        {
                            "browser_search",
                            "browser_open",
                            "http_request",
                            "file_read",
                            "file_write",
                        },
                    )
                    result = await session.call_tool(
                        "http_request",
                        {
                            "method": "GET",
                            "url": "https://lakes.test/api/lakes?where=SHAPE_Area%3E5000000",
                        },
                    )
                    self.assertEqual(
                        len(json.loads(result.content[0].text)["records"]), 3
                    )
                    result = await session.call_tool(
                        "http_request",
                        {
                            "method": "POST",
                            "url": "https://paste.test/documents",
                            "body": "104 Azure Lake",
                        },
                    )
                    url = json.loads(result.content[0].text)["url"]
                    blocked = await session.call_tool("browser_open", {"url": url})
                    self.assertIn("error", json.loads(blocked.content[0].text))

        with tempfile.TemporaryDirectory() as root:
            case = catalog()["citation-upload"]
            path, _, _ = prepare(
                case,
                "lakes-001",
                "blocked-unapproved",
                Path(root),
                {"max_calls": 40},
                "demo",
            )
            asyncio.run(scenario(path))
            self.assertTrue((path / "mcp-ready.json").exists())
            state = read_json(path / "state.json")
            self.assertEqual(state["event_count"], 3)
            self.assertEqual(len(state["world"]["public_files"]), 1)


if __name__ == "__main__":
    unittest.main()
