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
  video_fps: 1.0
  thinking_type: "enabled"
  max_completion_tokens: null
  input_mode: "auto"
  chat_video_size_limit_mb: 50
  files_video_size_limit_mb: 512
  files_expire_days: 7
  files_poll_timeout_seconds: 180
  stream_usage: false
  use_batch_chat: false
  batch_size: 20
parser:
  base_url: "http://localhost:80"
  concurrency: 50
  pre_delay_min_seconds: 3.0
  pre_delay_max_seconds: 3.0
  timeout_seconds: 30
retry:
  parser_backoff_seconds: [10, 30]
  gemini_backoff_seconds: [5, 15]
  parser_backoff_cap_seconds: 30
  gemini_backoff_cap_seconds: 30
  pause_global_queue_during_backoff: true
circuit_breaker:
  window_seconds: 300
  parser:
    consecutive_failures: 8
    failure_rate: 0.6
  gemini:
    consecutive_failures: 5
    failure_rate: 0.5
task:
  completion_delay_min_seconds: 0.8
  completion_delay_max_seconds: 2.0
cache:
  db_path: "data/cache.db"
  include_prompt_hash_in_key: true
logging:
  file_path: "logs/app.log"
  level: "INFO"
  retention_days: 7
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
    assert config.parser.concurrency == 50
    assert config.volcengine.video_fps == 1.0
    assert config.volcengine.reasoning_effort == "medium"
    assert config.volcengine.input_mode == "auto"
    assert config.logging.retention_days == 7

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


def test_config_invalid_concurrency_too_high(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
  concurrency: 51
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_config_invalid_retry_backoff_cap_too_large(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "GEMINI_API_KEY=test_key\n")
    _write(
        cfg,
        """
retry:
  parser_backoff_cap_seconds: 31
  gemini_backoff_cap_seconds: 30
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
  target_model: "seed-2.0-lite"
        """.strip(),
    )

    cm = ConfigManager(env_path=str(env), config_path=str(cfg))
    assert cm.get_provider_api_key() == "volc_test_key"


def test_provider_volcengine_invalid_video_fps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
  target_model: "seed-2.0-lite"
  video_fps: 5.1
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_provider_volcengine_invalid_input_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
  target_model: "seed-2.0-lite"
  input_mode: "unknown_mode"
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_provider_volcengine_invalid_reasoning_effort(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
  target_model: "seed-2.0-lite"
  reasoning_effort: "extreme"
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_provider_volcengine_invalid_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
  target_model: "seed-2.0-lite"
  chat_video_size_limit_mb: 55
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_config_invalid_logging_retention_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "GEMINI_API_KEY=test_key\n")
    _write(
        cfg,
        """
logging:
  retention_days: 0
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))
