from pathlib import Path
import tempfile
import unittest
import os
from unittest.mock import patch

from mrbench.config import JudgeConfig, load_config, read_env_file, judge_api_key


class ConfigTests(unittest.TestCase):
    def test_invalid_types_and_urls_fail_before_a_request(self):
        fixtures = [
            {"model": 42}, {"model": " "}, {"base_url": 42},
            {"base_url": "https://judge.test:bad/v1"}, {"base_url": "https://judge.test:0/v1"},
            {"base_url": "https://judge.test/path with spaces"},
            {"api_key_env": 42}, {"timeout": True}, {"timeout": "60"},
            {"max_output_tokens": True}, {"response_format": "unknown"},
            {"token_limit_parameter": "other"}, {"send_store": "false"},
        ]
        for settings in fixtures:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                JudgeConfig(**({"model": "fixture"} | settings))

    def test_malformed_or_unknown_judge_sections_are_clear_errors(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.toml"
            for content in ('judge = 42', '[judge]\nunknown = "value"', '[other]\nmodel = "fixture"'):
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    load_config(path)
            path.write_text('[judge]\nmodel = "fixture"')
            self.assertEqual(JudgeConfig(**load_config(path)["judge"]).model, "fixture")

    def test_env_file_is_literal_data_and_never_mutates_the_process(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {}, clear=True):
            path = Path(root) / ".env"
            path.write_text("# comment\nexport TEST_KEY='literal $(touch forbidden) $HOME' # tail\nOTHER=\"quoted value\"\n")
            values = read_env_file(path)
            self.assertEqual(values["TEST_KEY"], "literal $(touch forbidden) $HOME")
            self.assertEqual(values["OTHER"], "quoted value")
            config = JudgeConfig("fixture", api_key_env="TEST_KEY")
            self.assertEqual(judge_api_key(config, path), values["TEST_KEY"])
            self.assertNotIn("TEST_KEY", os.environ)
            with patch.dict(os.environ, {"TEST_KEY": "process-value"}):
                self.assertEqual(judge_api_key(config, path), "process-value")
            for text in ("broken", "A='unclosed", "A=1\nA=2"):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    read_env_file(path)


if __name__ == "__main__":
    unittest.main()
