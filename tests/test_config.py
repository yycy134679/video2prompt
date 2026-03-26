from __future__ import annotations

from pathlib import Path

import pytest

from video2prompt.config import ConfigManager
from video2prompt.errors import ConfigError
from video2prompt.runtime_paths import RuntimePaths


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_volcengine_only_config_loads_without_provider_or_gemini(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
  input_mode: "auto"
  stream: true
        """.strip(),
    )

    config = ConfigManager(env_path=str(env), config_path=str(cfg)).get_config()
    assert config.volcengine.model == "doubao-test-model"
    assert config.volcengine.input_mode == "auto"
    assert config.volcengine.stream is True


def test_override_updates_volcengine_and_parser_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
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


def test_save_mapping_persists_advanced_settings_to_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
  video_fps: 1.0
  thinking_type: "enabled"
  reasoning_effort: "medium"
parser:
  concurrency: 2
        """.strip(),
    )

    manager = ConfigManager(env_path=str(env), config_path=str(cfg))
    config = manager.save_mapping(
        {
            "parser.concurrency": 4,
            "volcengine.video_fps": 0.5,
            "volcengine.thinking_type": "auto",
            "volcengine.reasoning_effort": "high",
        }
    )

    assert config.parser.concurrency == 4
    assert config.volcengine.video_fps == 0.5
    assert config.volcengine.thinking_type == "auto"
    assert config.volcengine.reasoning_effort == "high"

    reloaded = ConfigManager(env_path=str(env), config_path=str(cfg)).get_config()
    assert reloaded.parser.concurrency == 4
    assert reloaded.volcengine.video_fps == 0.5
    assert reloaded.volcengine.thinking_type == "auto"
    assert reloaded.volcengine.reasoning_effort == "high"



def test_save_mapping_preserves_other_config_values_when_only_saving_concurrency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
  video_fps: 1.7
  thinking_type: "disabled"
  reasoning_effort: "low"
parser:
  concurrency: 2
        """.strip(),
    )

    manager = ConfigManager(env_path=str(env), config_path=str(cfg))
    config = manager.save_mapping({"parser.concurrency": 6})

    assert config.parser.concurrency == 6
    assert config.volcengine.video_fps == 1.7
    assert config.volcengine.thinking_type == "disabled"
    assert config.volcengine.reasoning_effort == "low"



def test_save_mapping_does_not_write_invalid_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    original = """
volcengine:
  model: "doubao-test-model"
  video_fps: 1.0
parser:
  concurrency: 2
    """.strip()
    _write(cfg, original)

    manager = ConfigManager(env_path=str(env), config_path=str(cfg))

    with pytest.raises(ConfigError):
        manager.save_mapping({"parser.concurrency": 0})

    assert cfg.read_text(encoding="utf-8").strip() == original



def test_config_invalid_concurrency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
parser:
  concurrency: 0
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_config_invalid_concurrency_too_high(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
parser:
  concurrency: 51
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_config_invalid_retry_backoff_cap_too_large(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
retry:
  parser_backoff_cap_seconds: 31
  model_backoff_cap_seconds: 30
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_get_volcengine_api_key_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg)).get_volcengine_api_key()


def test_config_manager_loads_without_api_key_until_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VOLCENGINE_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
        """.strip(),
    )

    manager = ConfigManager(env_path=str(env), config_path=str(cfg))

    assert manager.get_config().volcengine.model == "doubao-test-model"


def test_get_config_rewrites_relative_runtime_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
cache:
  db_path: "data/cache.db"
logging:
  file_path: "logs/app.log"
        """.strip(),
    )
    paths = RuntimePaths.for_bundle(bundle_root=tmp_path / "bundle", home_dir=tmp_path / "home")

    manager = ConfigManager(env_path=str(env), config_path=str(cfg), runtime_paths=paths)
    config = manager.get_config()

    assert config.cache.db_path == str(paths.data_dir / "cache.db")
    assert config.logging.file_path == str(paths.logs_dir / "app.log")


def test_volcengine_missing_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: ""
        """.strip(),
    )

    with pytest.raises(ConfigError, match="volcengine.model 不能为空"):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_volcengine_endpoint_id_is_no_longer_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    with pytest.raises(ConfigError, match="volcengine.model 不能为空"):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_volcengine_get_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
        """.strip(),
    )

    manager = ConfigManager(env_path=str(env), config_path=str(cfg))
    assert manager.get_volcengine_api_key() == "volc_test_key"


def test_volcengine_invalid_video_fps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
  video_fps: 5.1
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_volcengine_invalid_input_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
  input_mode: "unknown_mode"
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_volcengine_invalid_reasoning_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
  reasoning_effort: "extreme"
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_volcengine_invalid_video_url_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
  video_url_size_limit_mb: 55
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))


def test_config_invalid_logging_retention_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOLCENGINE_API_KEY", "volc_test_key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    env = tmp_path / ".env"
    cfg = tmp_path / "config.yaml"
    _write(env, "")
    _write(
        cfg,
        """
volcengine:
  model: "doubao-test-model"
logging:
  retention_days: 0
        """.strip(),
    )

    with pytest.raises(ConfigError):
        ConfigManager(env_path=str(env), config_path=str(cfg))
