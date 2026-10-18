"""Environment validation must match the advertised MCP schemas."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from mrbench.catalog import catalog
from mrbench.environments.simulation import Simulation


class TypedEnvironment(Simulation):
    @property
    def tools(self):
        return [
            {
                "name": "typed",
                "description": "Nested typed fixture",
                "inputSchema": deepcopy(self.sample["typed_schema"]),
            }
        ]

    def handle(self, name, args):
        self.world["files"]["/workspace/received"] = str(args)
        return {"accepted": True}, []


class ToolSchemaTests(unittest.TestCase):
    def setUp(self):
        c = catalog()["slack-injection"]
        s = deepcopy(c.samples[c.spec["default_sample"]])
        s["typed_schema"] = {
            "type": "object",
            "properties": {
                "rows": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 0, "maximum": 5},
                            "confirmed": {"type": "boolean"},
                        },
                        "required": ["score", "confirmed"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["rows"],
            "additionalProperties": False,
        }
        self.env = TypedEnvironment(c, s, c.condition("main"))

    def test_nested_types_ranges_and_additional_fields_are_recorded_errors(self):
        for args in (
            {"rows": [{"score": True, "confirmed": True}]},
            {"rows": [{"score": 6, "confirmed": True}]},
            {"rows": [{"score": 4, "confirmed": "true"}]},
            {"rows": []},
            {"rows": [{"score": 4, "confirmed": True, "extra": "no"}]},
            {"rows": [{"score": 4, "confirmed": True}], "extra": "no"},
        ):
            result = self.env.call("typed", args)
            self.assertIn("error", result)
            self.assertNotIn("/workspace/received", self.env.world["files"])
        self.assertEqual(len(self.env.events), 6)
        self.assertTrue(
            self.env.call("typed", {"rows": [{"score": 4, "confirmed": True}]})[
                "accepted"
            ]
        )

    def test_remote_schema_references_never_open_a_network_connection(self):
        self.env.sample["typed_schema"] = {
            "type": "object",
            "properties": {"value": {"$ref": "https://example.com/schema"}},
            "required": ["value"],
        }
        with patch("socket.socket", side_effect=AssertionError("Network access")):
            result = self.env.call("typed", {"value": "test"})
        self.assertIn("cannot retrieve external references", result["error"])


if __name__ == "__main__":
    unittest.main()
