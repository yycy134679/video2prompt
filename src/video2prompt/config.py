"""配置管理。"""

from __future__ import annotations

import copy
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .errors import ConfigError
from .models import (
    AppConfig,
    CacheConfig,
    CircuitBreakerConfig,
    CircuitServiceConfig,
    LoggingConfig,
    ParserConfig,
    RetryConfig,
    TaskConfig,
    VolcengineConfig,
)
from .runtime_paths import RuntimePaths


class ConfigManager:
    """加载与校验配置，支持运行时覆盖。"""

    def __init__(
        self,
        env_path: str = ".env",
        config_path: str = "config.yaml",
        runtime_paths: RuntimePaths | None = None,
    ):
        self._env_path = Path(env_path)
        self._config_path = Path(config_path)
        self._runtime_paths = runtime_paths
        self._overrides: dict[str, Any] = {}
        self._base_config = AppConfig()
        load_dotenv(self._env_path, override=False)
        self._reload_base_config()

    def _reload_base_config(self) -> None:
        raw = self._load_yaml()
        self._base_config = self._build_app_config(raw)

    def _load_yaml(self) -> dict[str, Any]:
        if not self._config_path.exists():
            raise ConfigError(f"配置文件不存在: {self._config_path}")
        try:
            with self._config_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"config.yaml 解析失败: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("config.yaml 顶层必须是对象")
        return data

    def get_volcengine_api_key(self) -> str:
        value = os.getenv("VOLCENGINE_API_KEY", "").strip() or os.getenv("ARK_API_KEY", "").strip()
        if not value:
            raise ConfigError("缺少 VOLCENGINE_API_KEY（或 ARK_API_KEY），请在 .env 中配置")
        return value

    def get_provider_api_key(self) -> str:
        return self.get_volcengine_api_key()

    def override(self, **kwargs: Any) -> None:
        """运行时覆盖配置。支持点路径键，例如 parser.concurrency=2。"""

        if not kwargs:
            return
        for key, value in kwargs.items():
            if not isinstance(key, str) or not key:
                raise ConfigError("override 的键必须是非空字符串")
            self._set_dotted_value(self._overrides, key, value)
        # 覆盖后立刻校验
        _ = self.get_config()

    def override_mapping(self, mapping: dict[str, Any]) -> None:
        for key, value in mapping.items():
            self.override(**{key: value})

    def clear_overrides(self) -> None:
        self._overrides = {}

    def get_config(self) -> AppConfig:
        base = asdict(self._base_config)
        merged = copy.deepcopy(base)
        self._deep_merge(merged, self._overrides)
        config = self._build_app_config(merged)
        return self._apply_runtime_file_overrides(config)

    def _apply_runtime_file_overrides(self, config: AppConfig) -> AppConfig:
        if self._runtime_paths is None:
            return config

        if not Path(config.cache.db_path).is_absolute():
            config.cache.db_path = str(self._runtime_paths.data_dir / Path(config.cache.db_path).name)
        if not Path(config.logging.file_path).is_absolute():
            config.logging.file_path = str(
                self._runtime_paths.logs_dir / Path(config.logging.file_path).name
            )
        return config

    @staticmethod
    def _set_dotted_value(target: dict[str, Any], dotted_key: str, value: Any) -> None:
        keys = dotted_key.split(".")
        node = target
        for key in keys[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]
        node[keys[-1]] = value

    @classmethod
    def _deep_merge(cls, target: dict[str, Any], patch: dict[str, Any]) -> None:
        for key, value in patch.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                cls._deep_merge(target[key], value)
            else:
                target[key] = value

    def _build_app_config(self, data: dict[str, Any]) -> AppConfig:
        defaults = asdict(AppConfig())
        merged = copy.deepcopy(defaults)
        self._deep_merge(merged, data)

        volcengine_data = self._as_dict(merged, "volcengine")
        volcengine_data.pop("endpoint_id", None)
        volcengine = VolcengineConfig(**volcengine_data)
        volcengine.thinking_type = self._normalize_volc_thinking_type(volcengine.thinking_type)
        volcengine.reasoning_effort = self._normalize_volc_reasoning_effort(volcengine.reasoning_effort)
        volcengine.input_mode = self._normalize_volc_input_mode(volcengine.input_mode)
        parser = ParserConfig(**self._as_dict(merged, "parser"))
        retry = RetryConfig(**self._as_dict(merged, "retry"))

        cb_data = self._as_dict(merged, "circuit_breaker")
        cb = CircuitBreakerConfig(
            window_seconds=int(cb_data.get("window_seconds", 300)),
            parser=CircuitServiceConfig(**self._as_dict(cb_data, "parser")),
            model=CircuitServiceConfig(**self._as_dict(cb_data, "model")),
        )

        task = TaskConfig(**self._as_dict(merged, "task"))
        cache = CacheConfig(**self._as_dict(merged, "cache"))
        logging = LoggingConfig(**self._as_dict(merged, "logging"))

        config = AppConfig(
            volcengine=volcengine,
            parser=parser,
            retry=retry,
            circuit_breaker=cb,
            task=task,
            cache=cache,
            logging=logging,
        )
        self._validate(config)
        return config

    @staticmethod
    def _as_dict(data: dict[str, Any], key: str) -> dict[str, Any]:
        val = data.get(key, {})
        if not isinstance(val, dict):
            raise ConfigError(f"配置项 {key} 必须是对象")
        return val

    @staticmethod
    def _validate(config: AppConfig) -> None:
        if not (1 <= config.parser.concurrency <= 50):
            raise ConfigError("parser.concurrency 必须在 1-50 之间")
        if config.parser.pre_delay_min_seconds < 0 or config.parser.pre_delay_max_seconds < 0:
            raise ConfigError("parser.pre_delay_* 必须 >= 0")
        if config.parser.pre_delay_min_seconds > config.parser.pre_delay_max_seconds:
            raise ConfigError("parser.pre_delay_min_seconds 不能大于 pre_delay_max_seconds")

        if config.parser.timeout_seconds <= 0:
            raise ConfigError("timeout_seconds 必须 > 0")
        if config.volcengine.timeout_seconds <= 0:
            raise ConfigError("volcengine.timeout_seconds 必须 > 0")
        if not config.volcengine.model.strip():
            raise ConfigError("volcengine.model 不能为空")
        if not (0.2 <= float(config.volcengine.video_fps) <= 5):
            raise ConfigError("volcengine.video_fps 必须在 [0.2,5] 区间")
        thinking_type = ConfigManager._normalize_volc_thinking_type(config.volcengine.thinking_type)
        if thinking_type not in {"enabled", "disabled", "auto"}:
            raise ConfigError("volcengine.thinking_type 必须是 enabled/disabled/auto")
        reasoning_effort = ConfigManager._normalize_volc_reasoning_effort(config.volcengine.reasoning_effort)
        if reasoning_effort not in {"minimal", "low", "medium", "high"}:
            raise ConfigError("volcengine.reasoning_effort 必须是 minimal/low/medium/high")
        if config.volcengine.max_output_tokens is not None and int(config.volcengine.max_output_tokens) <= 0:
            raise ConfigError("volcengine.max_output_tokens 必须为正整数或 null")
        input_mode = ConfigManager._normalize_volc_input_mode(config.volcengine.input_mode)
        if input_mode not in {"auto", "video_url", "file_id"}:
            raise ConfigError("volcengine.input_mode 必须是 auto/video_url/file_id")
        if config.volcengine.video_url_size_limit_mb <= 0 or config.volcengine.video_url_size_limit_mb > 50:
            raise ConfigError("volcengine.video_url_size_limit_mb 必须在 1-50 之间")
        if config.volcengine.files_video_size_limit_mb <= 0 or config.volcengine.files_video_size_limit_mb > 512:
            raise ConfigError("volcengine.files_video_size_limit_mb 必须在 1-512 之间")
        if config.volcengine.video_url_size_limit_mb > config.volcengine.files_video_size_limit_mb:
            raise ConfigError("volcengine.video_url_size_limit_mb 不能大于 files_video_size_limit_mb")
        if not (1 <= config.volcengine.files_expire_days <= 30):
            raise ConfigError("volcengine.files_expire_days 必须在 1-30 之间")
        if config.volcengine.files_poll_timeout_seconds <= 0:
            raise ConfigError("volcengine.files_poll_timeout_seconds 必须 > 0")
        if not isinstance(config.volcengine.stream, bool):
            raise ConfigError("volcengine.stream 必须是布尔值")

        if not config.retry.parser_backoff_seconds or not config.retry.model_backoff_seconds:
            raise ConfigError("retry backoff 列表不能为空")
        if any(int(x) <= 0 for x in config.retry.parser_backoff_seconds):
            raise ConfigError("retry.parser_backoff_seconds 必须为正整数")
        if any(int(x) <= 0 for x in config.retry.model_backoff_seconds):
            raise ConfigError("retry.model_backoff_seconds 必须为正整数")
        if config.retry.parser_backoff_cap_seconds <= 0 or config.retry.model_backoff_cap_seconds <= 0:
            raise ConfigError("retry backoff cap 必须 > 0")
        if config.retry.parser_backoff_cap_seconds > 30 or config.retry.model_backoff_cap_seconds > 30:
            raise ConfigError("retry backoff cap 必须 <= 30")

        if not (0 <= config.circuit_breaker.parser.failure_rate <= 1):
            raise ConfigError("circuit_breaker.parser.failure_rate 必须在 [0,1]")
        if not (0 <= config.circuit_breaker.model.failure_rate <= 1):
            raise ConfigError("circuit_breaker.model.failure_rate 必须在 [0,1]")
        if config.circuit_breaker.parser.consecutive_failures <= 0:
            raise ConfigError("circuit_breaker.parser.consecutive_failures 必须 > 0")
        if config.circuit_breaker.model.consecutive_failures <= 0:
            raise ConfigError("circuit_breaker.model.consecutive_failures 必须 > 0")

        if config.task.completion_delay_min_seconds < 0 or config.task.completion_delay_max_seconds < 0:
            raise ConfigError("task.completion_delay_* 必须 >= 0")
        if config.task.completion_delay_min_seconds > config.task.completion_delay_max_seconds:
            raise ConfigError("task.completion_delay_min_seconds 不能大于 completion_delay_max_seconds")

        level = config.logging.level.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError("logging.level 必须是 DEBUG/INFO/WARNING/ERROR/CRITICAL")
        if not config.logging.file_path.strip():
            raise ConfigError("logging.file_path 不能为空")
        if config.logging.retention_days <= 0:
            raise ConfigError("logging.retention_days 必须 > 0")

    @staticmethod
    def _normalize_volc_thinking_type(value: str) -> str:
        return (value or "").strip().lower()

    @staticmethod
    def _normalize_volc_reasoning_effort(value: str) -> str:
        normalized = (value or "").strip().lower()
        return normalized or "medium"

    @staticmethod
    def _normalize_volc_input_mode(value: str) -> str:
        return (value or "").strip().lower()
