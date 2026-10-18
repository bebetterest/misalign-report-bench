"""Explicit judge settings and optional literal credential-file loading."""

from dataclasses import dataclass
from pathlib import Path
import re
import os
import shlex
import tomllib
from urllib.parse import urlsplit


@dataclass(frozen=True)
class JudgeConfig:
    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    timeout: int = 60
    max_output_tokens: int = 4096
    response_format: str = "json_schema"
    token_limit_parameter: str = "max_completion_tokens"
    send_store: bool = True

    def __post_init__(self):
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Judge model must be a nonempty string")
        if not isinstance(self.base_url, str):
            raise ValueError("Judge base_url must be a clean http(s) URL")
        try:
            url = urlsplit(self.base_url)
            valid_url = (
                url.scheme in ("http", "https")
                and url.hostname
                and (url.port is None or 1 <= url.port <= 65535)
                and not any((url.username, url.password, url.query, url.fragment))
                and not any(character.isspace() for character in self.base_url)
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError("Judge base_url must be a clean http(s) URL with a valid port")
        if not isinstance(self.api_key_env, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_env
        ):
            raise ValueError("Invalid judge API key environment variable")
        if (
            type(self.timeout) is not int
            or not 1 <= self.timeout <= 600
            or type(self.max_output_tokens) is not int
            or not 256 <= self.max_output_tokens <= 32768
            or self.response_format not in ("json_schema", "json_object")
            or self.token_limit_parameter not in ("max_completion_tokens", "max_tokens")
            or type(self.send_store) is not bool
        ):
            raise ValueError("Invalid judge timeout, output limit, response format or compatibility settings")


def read_env_file(path: Path) -> dict[str, str]:
    """Read KEY=value data, never source a shell file or expand substitutions.

    Supports single-line values, quotes, comments and an optional export prefix.
    Explicit process variables take precedence when selecting the judge key.
    """
    values = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, raw = line.partition("=")
        key = key.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in values:
            raise ValueError(f"Invalid or duplicate environment assignment on line {number}")
        try:
            values[key] = " ".join(shlex.split(raw.strip(), comments=True, posix=True))
        except ValueError:
            raise ValueError(f"Invalid quoted environment value on line {number}") from None
    return values


def judge_api_key(config: JudgeConfig, env_file: Path | None = None) -> str | None:
    values = read_env_file(env_file) if env_file is not None else {}
    return os.environ.get(config.api_key_env) or values.get(config.api_key_env)


def load_config(path: Path | None) -> dict:
    if path is None:
        return {}
    value = tomllib.loads(path.read_text(encoding="utf-8"))
    if set(value) - {"judge"}:
        raise ValueError("Config currently supports only a [judge] section")
    settings = value.get("judge", {})
    if not isinstance(settings, dict):
        raise ValueError("Judge configuration must be a [judge] table")
    unknown = set(settings) - set(JudgeConfig.__dataclass_fields__)
    if unknown:
        raise ValueError("Unknown judge settings: " + ", ".join(sorted(unknown)))
    return value
