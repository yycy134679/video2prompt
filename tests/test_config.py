from __future__ import annotations

from pathlib import Path

import pytest

from video2prompt.config import ConfigManager
from video2prompt.errors import ConfigError


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_volcengine_only_config_loads_without_provider_or_gemini(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
  input_mode: "auto"
  stream: true
        """.strip(),
    )

    config = ConfigManager(env_path=str(env), config_path=str(cfg)).get_config()
    assert config.volcengine.endpoint_id == "ep-test"
    assert config.volcengine.input_mode == "auto"
    assert config.volcengine.stream is True


def test_override_updates_volcengine_and_parser_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
  input_mode: "auto"
parser:
  concurrency: 5
        """.strip(),
    )

    manager = ConfigManager(env_path=str(env), config_path=str(cfg))
    manager.override(**{"volcengine.video_fps": 0.5, "parser.concurrency": 2})

    config = manager.get_config()
    assert config.volcengine.video_fps == 0.5
    assert config.parser.concurrency == 2


def test_config_invalid_concurrency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
parser:
  concurrency: 0
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_config_invalid_concurrency_too_high(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
parser:
  concurrency: 51
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_config_invalid_retry_backoff_cap_too_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
retry:
  parser_backoff_cap_seconds: 31
  model_backoff_cap_seconds: 30
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_get_volcengine_api_key_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_volcengine_missing_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: ""
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_volcengine_get_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
        """.strip(),
    )

    manager = ConfigManager(env_path=str(env), config_path=str(cfg))
    assert manager.get_volcengine_api_key() == "volc_test_key"


def test_volcengine_invalid_video_fps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
  video_fps: 5.1
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_volcengine_invalid_input_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
  input_mode: "unknown_mode"
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_volcengine_invalid_reasoning_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
  reasoning_effort: "extreme"
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_volcengine_invalid_video_url_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
  video_url_size_limit_mb: 55
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_config_invalid_logging_retention_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  endpoint_id: "ep-test"
logging:
  retention_days: 0
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))
