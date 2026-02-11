from __future__ import annotations

from pathlib import Path

import pytest

from video2prompt.config import ConfigManager
from video2prompt.errors import ConfigError


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_config_load_and_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"

    _write(env, "GEMINI_API_KEY=test_key\n")
    _write(
        cfg,
        """
provider: "gemini"
gemini:
  base_url: "https://api.huandutech.com"
  model: "gemini-3-flash-preview"
  thinking_level: "high"
  media_resolution: "media_resolution_medium"
  video_fps: 2.0
  fps_fallback: 1.0
  timeout_seconds: 90
volcengine:
  base_url: "https://ark.cn-beijing.volces.com/api/v3"
  endpoint_id: "ep-test"
  target_model: "doubao-seed-1-8-251228"
  timeout_seconds: 90
parser:
  base_url: "http://localhost:80"
  concurrency: 3
  pre_delay_min_seconds: 1.5
  pre_delay_max_seconds: 4.0
  timeout_seconds: 30
retry:
  parser_backoff_seconds: [10, 30, 120, 300]
  gemini_backoff_seconds: [5, 15, 60, 180]
  parser_backoff_cap_seconds: 600
  gemini_backoff_cap_seconds: 300
  pause_global_queue_during_backoff: true
circuit_breaker:
  window_seconds: 300
  parser:
    consecutive_failures: 8
    failure_rate: 0.6
  gemini:
    consecutive_failures: 5
    failure_rate: 0.5
batch:
  size: 100
  rest_min_minutes: 5
  rest_max_minutes: 15
task:
  completion_delay_min_seconds: 0.8
  completion_delay_max_seconds: 2.0
cache:
  db_path: "data/cache.db"
  include_prompt_hash_in_key: true
logging:
  file_path: "logs/app.log"
  level: "INFO"
        """.strip(),
    )

    cm = ConfigManager(env_path=str(env), config_path=str(cfg))
    assert cm.get_gemini_api_key() == "test_key"
    assert cm.get_provider_api_key() == "test_key"

    config = cm.get_config()
    assert config.provider == "gemini"
    assert config.gemini.video_fps == 2.0
    assert config.gemini.thinking_level == "high"
    assert config.gemini.media_resolution == "media_resolution_medium"
    assert config.parser.concurrency == 3

    cm.override(**{"gemini.video_fps": 0.5, "parser.concurrency": 2})
    updated = cm.get_config()
    assert updated.gemini.video_fps == 0.5
    assert updated.parser.concurrency == 2


def test_config_invalid_concurrency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "GEMINI_API_KEY=test_key\n")
    _write(
        cfg,
        """
parser:
  concurrency: 0
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_config_invalid_media_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "GEMINI_API_KEY=test_key\n")
    _write(
        cfg,
        """
gemini:
  media_resolution: "media_resolution_ultra_high"
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_get_api_key_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(cfg, "{}")

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_provider_volcengine_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
provider: "volcengine"
volcengine:
  endpoint_id: "ep-test"
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_provider_volcengine_missing_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "VOLCENGINE_API_KEY=volc_test_key\n")
    _write(
        cfg,
        """
provider: "volcengine"
volcengine:
  endpoint_id: ""
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_provider_volcengine_get_provider_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "VOLCENGINE_API_KEY=volc_test_key\n")
    _write(
        cfg,
        """
provider: "volcengine"
volcengine:
  endpoint_id: "ep-test"
  target_model: "doubao-seed-1-8-251228"
        """.strip(),
    )

    cm = ConfigManager(env_path=str(env), config_path=str(cfg))
    assert cm.get_provider_api_key() == "volc_test_key"
