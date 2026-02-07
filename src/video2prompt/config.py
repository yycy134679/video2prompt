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
    BatchConfig,
    CacheConfig,
    CircuitBreakerConfig,
    CircuitServiceConfig,
    GeminiConfig,
    LoggingConfig,
    ParserConfig,
    RetryConfig,
    TaskConfig,
)


class ConfigManager:
    """加载与校验配置，支持运行时覆盖。"""

    def __init__(self, env_path: str = ".env", config_path: str = "config.yaml"):
        self._env_path = Path(env_path)
        self._config_path = Path(config_path)
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

    def get_gemini_api_key(self) -> str:
        value = os.getenv("GEMINI_API_KEY", "").strip()
        if not value:
            raise ConfigError("缺少 GEMINI_API_KEY，请在 .env 中配置")
        return value

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
        return self._build_app_config(merged)

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

        gemini = GeminiConfig(**self._as_dict(merged, "gemini"))
        parser = ParserConfig(**self._as_dict(merged, "parser"))
        retry = RetryConfig(**self._as_dict(merged, "retry"))

        cb_data = self._as_dict(merged, "circuit_breaker")
        cb = CircuitBreakerConfig(
            window_seconds=int(cb_data.get("window_seconds", 300)),
            parser=CircuitServiceConfig(**self._as_dict(cb_data, "parser")),
            gemini=CircuitServiceConfig(**self._as_dict(cb_data, "gemini")),
        )

        batch = BatchConfig(**self._as_dict(merged, "batch"))
        task = TaskConfig(**self._as_dict(merged, "task"))
        cache = CacheConfig(**self._as_dict(merged, "cache"))
        logging = LoggingConfig(**self._as_dict(merged, "logging"))

        config = AppConfig(
            gemini=gemini,
            parser=parser,
            retry=retry,
            circuit_breaker=cb,
            batch=batch,
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
        if not (1 <= config.parser.concurrency <= 5):
            raise ConfigError("parser.concurrency 必须在 1-5 之间")
        if config.parser.pre_delay_min_seconds < 0 or config.parser.pre_delay_max_seconds < 0:
            raise ConfigError("parser.pre_delay_* 必须 >= 0")
        if config.parser.pre_delay_min_seconds > config.parser.pre_delay_max_seconds:
            raise ConfigError("parser.pre_delay_min_seconds 不能大于 pre_delay_max_seconds")

        if config.gemini.video_fps <= 0:
            raise ConfigError("gemini.video_fps 必须 > 0")
        if config.gemini.fps_fallback <= 0:
            raise ConfigError("gemini.fps_fallback 必须 > 0")
        thinking_level = ConfigManager._normalize_thinking_level(config.gemini.thinking_level)
        allowed_thinking_levels = {"minimal", "low", "medium", "high"}
        if thinking_level not in allowed_thinking_levels:
            raise ConfigError("gemini.thinking_level 必须是 minimal/low/medium/high")

        media_resolution = ConfigManager._normalize_media_resolution(config.gemini.media_resolution)
        allowed_media_resolution = {
            "media_resolution_low",
            "media_resolution_medium",
            "media_resolution_high",
        }
        if media_resolution not in allowed_media_resolution:
            raise ConfigError("gemini.media_resolution 必须是 media_resolution_low/media_resolution_medium/media_resolution_high")

        if config.gemini.timeout_seconds <= 0 or config.parser.timeout_seconds <= 0:
            raise ConfigError("timeout_seconds 必须 > 0")

        if not config.retry.parser_backoff_seconds or not config.retry.gemini_backoff_seconds:
            raise ConfigError("retry backoff 列表不能为空")
        if any(int(x) <= 0 for x in config.retry.parser_backoff_seconds):
            raise ConfigError("retry.parser_backoff_seconds 必须为正整数")
        if any(int(x) <= 0 for x in config.retry.gemini_backoff_seconds):
            raise ConfigError("retry.gemini_backoff_seconds 必须为正整数")
        if config.retry.parser_backoff_cap_seconds <= 0 or config.retry.gemini_backoff_cap_seconds <= 0:
            raise ConfigError("retry backoff cap 必须 > 0")

        if not (0 <= config.circuit_breaker.parser.failure_rate <= 1):
            raise ConfigError("circuit_breaker.parser.failure_rate 必须在 [0,1]")
        if not (0 <= config.circuit_breaker.gemini.failure_rate <= 1):
            raise ConfigError("circuit_breaker.gemini.failure_rate 必须在 [0,1]")
        if config.circuit_breaker.parser.consecutive_failures <= 0:
            raise ConfigError("circuit_breaker.parser.consecutive_failures 必须 > 0")
        if config.circuit_breaker.gemini.consecutive_failures <= 0:
            raise ConfigError("circuit_breaker.gemini.consecutive_failures 必须 > 0")

        if not (50 <= config.batch.size <= 200):
            raise ConfigError("batch.size 必须在 50-200 之间")
        if config.batch.rest_min_minutes <= 0 or config.batch.rest_max_minutes <= 0:
            raise ConfigError("batch.rest_* 必须 > 0")
        if config.batch.rest_min_minutes > config.batch.rest_max_minutes:
            raise ConfigError("batch.rest_min_minutes 不能大于 rest_max_minutes")

        if config.task.completion_delay_min_seconds < 0 or config.task.completion_delay_max_seconds < 0:
            raise ConfigError("task.completion_delay_* 必须 >= 0")
        if config.task.completion_delay_min_seconds > config.task.completion_delay_max_seconds:
            raise ConfigError("task.completion_delay_min_seconds 不能大于 completion_delay_max_seconds")

        level = config.logging.level.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError("logging.level 必须是 DEBUG/INFO/WARNING/ERROR/CRITICAL")
        if not config.logging.file_path.strip():
            raise ConfigError("logging.file_path 不能为空")

    @staticmethod
    def _normalize_thinking_level(value: str) -> str:
        return (value or "").strip().lower()

    @staticmethod
    def _normalize_media_resolution(value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized.startswith("media_resolution_"):
            return normalized
        if normalized.startswith("mediaresolution_"):
            return normalized.replace("mediaresolution_", "media_resolution_", 1)
        return normalized
