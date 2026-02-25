"""核心数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskState(str, Enum):
    """任务状态枚举。"""

    WAITING = "等待中"
    PARSING = "解析中"
    INTERVAL = "等待间隔"
    INTERPRETING = "模型解读中"
    COMPLETED = "完成"
    FAILED = "失败"
    CIRCUIT_BREAK = "熔断停止"
    CANCELLED = "已取消"


@dataclass
class GeminiConfig:
    base_url: str = "https://api.huandutech.com"
    model: str = "gemini-3-flash-preview"
    thinking_level: str = "high"
    media_resolution: str = "media_resolution_medium"
    video_fps: float = 2.0
    fps_fallback: float = 1.0
    timeout_seconds: int = 90


@dataclass
class VolcengineConfig:
    base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    endpoint_id: str = ""
    target_model: str = "doubao-seed-1-8-251228"
    timeout_seconds: int = 90
    # 视频大小上限（MB），超过此值跳过模型调用；0 表示不限制
    video_size_limit_mb: int = 50


@dataclass
class ParserConfig:
    base_url: str = "http://localhost:80"
    concurrency: int = 3
    pre_delay_min_seconds: float = 1.5
    pre_delay_max_seconds: float = 4.0
    timeout_seconds: int = 30


@dataclass
class RetryConfig:
    parser_backoff_seconds: list[int] = field(default_factory=lambda: [10, 30, 120, 300])
    gemini_backoff_seconds: list[int] = field(default_factory=lambda: [5, 15, 60, 180])
    parser_backoff_cap_seconds: int = 600
    gemini_backoff_cap_seconds: int = 300
    pause_global_queue_during_backoff: bool = True


@dataclass
class CircuitServiceConfig:
    consecutive_failures: int
    failure_rate: float


@dataclass
class CircuitBreakerConfig:
    window_seconds: int = 300
    parser: CircuitServiceConfig = field(
        default_factory=lambda: CircuitServiceConfig(consecutive_failures=8, failure_rate=0.6)
    )
    gemini: CircuitServiceConfig = field(
        default_factory=lambda: CircuitServiceConfig(consecutive_failures=5, failure_rate=0.5)
    )


@dataclass
class TaskConfig:
    completion_delay_min_seconds: float = 0.8
    completion_delay_max_seconds: float = 2.0


@dataclass
class CacheConfig:
    db_path: str = "data/cache.db"
    include_prompt_hash_in_key: bool = True


@dataclass
class LoggingConfig:
    file_path: str = "logs/app.log"
    level: str = "INFO"


@dataclass
class AppConfig:
    provider: str = "gemini"
    gemini: GeminiConfig = field(default_factory=GeminiConfig)
    volcengine: VolcengineConfig = field(default_factory=VolcengineConfig)
    parser: ParserConfig = field(default_factory=ParserConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    task: TaskConfig = field(default_factory=TaskConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


@dataclass
class TaskInput:
    pid: str
    link: str
    is_valid: bool = True
    error: str = ""


@dataclass
class ValidationResult:
    is_valid: bool
    error_message: str = ""
    pid_count: int = 0
    link_count: int = 0


@dataclass
class ParseResult:
    aweme_id: str
    video_url: str
    raw_data: dict


@dataclass
class CachedResult:
    link_hash: str
    prompt_hash: str
    aweme_id: str
    video_url: str
    gemini_output: str
    fps_used: float
    created_at: datetime


@dataclass
class Task:
    pid: str
    original_link: str
    aweme_id: str = ""
    video_url: str = ""
    state: TaskState = TaskState.WAITING
    parse_retries: int = 0
    gemini_retries: int = 0
    error_message: str = ""
    gemini_output: str = ""
    start_time: datetime | None = None
    end_time: datetime | None = None
    cache_hit: bool = False
    fps_used: float = 0.0

    @property
    def duration_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        end = self.end_time or datetime.now()
        return max((end - self.start_time).total_seconds(), 0.0)
