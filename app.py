"""Streamlit 入口。"""

from __future__ import annotations

import asyncio
import copy
import contextlib
import hashlib
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, MutableMapping
from uuid import uuid4

import httpx
import streamlit as st
import yaml


def _ensure_local_src_on_path() -> None:
    src_path = Path(__file__).resolve().parent / "src"
    if not src_path.is_dir():
        return
    src_path_str = str(src_path)
    if src_path_str not in sys.path:
        sys.path.insert(0, src_path_str)


_ensure_local_src_on_path()

from video2prompt.cache_store import CacheStore
from video2prompt.circuit_breaker import CircuitBreaker
from video2prompt.config import ConfigManager
from video2prompt.duration_check_runner import DurationCheckRunner
from video2prompt.duration_excel_exporter import DurationExcelExporter
from video2prompt.errors import ConfigError
from video2prompt.excel_exporter import ExcelExporter
from video2prompt.logging_utils import setup_logging
from video2prompt.markdown_exporter import MarkdownExporter
from video2prompt.models import AppMode, Task, TaskInput
from video2prompt.parser_client import (
    COOKIE_REQUIRED_MESSAGE,
    COOKIE_RETRY_HINT,
    ParserClient,
)
from video2prompt.review_result import DEFAULT_REVIEW_PROMPT
from video2prompt.runtime_paths import RuntimePaths
from video2prompt.task_scheduler import TaskScheduler
from video2prompt.user_state_store import UserStateStore
from video2prompt.validator import InputValidator
from video2prompt.volcengine_files_client import VolcengineFilesClient
from video2prompt.volcengine_responses_client import VolcengineResponsesClient

OUTPUT_FORMAT_PLAIN_TEXT = "plain_text"
OUTPUT_FORMAT_JSON = "json"
OUTPUT_FORMAT_LABEL_TO_VALUE = {
    "纯文本（默认）": OUTPUT_FORMAT_PLAIN_TEXT,
    "JSON": OUTPUT_FORMAT_JSON,
}
OUTPUT_FORMAT_VALUE_TO_LABEL = {
    value: label for label, value in OUTPUT_FORMAT_LABEL_TO_VALUE.items()
}
SESSION_EXCEL_DOWNLOAD = "excel_download_payload"
SESSION_MARKDOWN_DOWNLOAD = "markdown_download_payload"
SESSION_DURATION_SHORT_DOWNLOAD = "duration_short_download_payload"
SESSION_DURATION_LONG_FAILED_DOWNLOAD = "duration_long_failed_download_payload"
SESSION_RUN_CONTROLLER = "run_controller_id"
SESSION_COOKIE_NOTICE = "cookie_notice"
SESSION_COOKIE_FAILURE = "cookie_failure"
SESSION_COOKIE_INPUT_RESET = "cookie_input_reset"
SESSION_AI_SETTINGS_NOTICE = "ai_settings_notice"
SESSION_AI_SETTINGS_INPUT_RESET = "ai_settings_input_reset"
SESSION_AI_SETTINGS_RESOLVED_API_KEY = "ai_settings_resolved_api_key"
SESSION_AI_SETTINGS_RESOLVED_MODEL = "ai_settings_resolved_model"
SESSION_ADVANCED_SETTINGS_NOTICE = "advanced_settings_notice"
SESSION_ADVANCED_PARSER_CONCURRENCY = "advanced_parser_concurrency"
SESSION_ADVANCED_VIDEO_FPS = "advanced_video_fps"
SESSION_ADVANCED_THINKING_TYPE = "advanced_thinking_type"
SESSION_ADVANCED_REASONING_EFFORT = "advanced_reasoning_effort"
SESSION_LAST_RUN_FINISHED = "last_run_finished"
SESSION_LAST_RUN_CANCELLED = "last_run_cancelled"
SESSION_LAST_RUN_ERROR_MESSAGE = "last_run_error_message"
SESSION_VIDEO_PROMPT = "video_prompt"
SESSION_CATEGORY_ANALYSIS_PROMPT = "category_analysis_prompt"
SESSION_TRANSLATION_COMPLIANCE_PROMPT = "translation_compliance_prompt"
SESSION_VIDEO_PROMPT_OUTPUT_FORMAT = "video_prompt_output_format"
SESSION_PROMPT_EDITOR_MODE = "prompt_editor_mode"
SESSION_PROMPT_EDITOR_REFRESH_MODE = "prompt_editor_refresh_mode"
SESSION_PROMPT_NOTICE = "prompt_notice"
SETTING_VIDEO_PROMPT = "prompt.video_prompt"
SETTING_CATEGORY_ANALYSIS_PROMPT = "prompt.category_analysis"
SETTING_TRANSLATION_COMPLIANCE_PROMPT = "prompt.translation_compliance"
SETTING_VIDEO_PROMPT_CUSTOM_ENABLED = "prompt.video_prompt_custom_enabled"
SETTING_CATEGORY_ANALYSIS_PROMPT_CUSTOM_ENABLED = (
    "prompt.category_analysis_custom_enabled"
)
SETTING_VIDEO_PROMPT_OUTPUT_FORMAT = "output_format.video_prompt"
@dataclass
class RunController:
    tasks: list[Task]
    show_category: bool
    is_duration_mode: bool
    app_mode_value: str
    default_user_prompt: str
    output_format: str
    running: bool = False
    finished: bool = False
    stop_requested: bool = False
    cancelled: bool = False
    error_message: str = ""
    loop: asyncio.AbstractEventLoop | None = None
    cancel_event: asyncio.Event | None = None
    thread: threading.Thread | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(frozen=True)
class ResolvedRunSettings:
    prompt_text: str
    output_format: str


@dataclass(frozen=True)
class ResolvedAiSettings:
    api_key: str
    model: str


@dataclass(frozen=True)
class RuntimeFiles:
    resource_root: Path
    app_support_dir: Path
    env_path: Path
    config_path: Path
    exports_dir: Path
    ffprobe_path: Path
    video_prompt_template_path: Path
    category_prompt_template_path: Path
    translation_template_path: Path
    excel_template_path: Path


def resolve_runtime_files(environ: Mapping[str, str] | None = None) -> RuntimeFiles:
    env = environ or os.environ
    resource_root = Path(env.get("VIDEO2PROMPT_RESOURCE_ROOT", "."))
    app_support_dir = Path(
        env.get(
            "VIDEO2PROMPT_APP_SUPPORT_DIR",
            str(Path.home() / "Library" / "Application Support" / "video2prompt"),
        )
    )
    env_path = Path(env.get("VIDEO2PROMPT_ENV_PATH", str(app_support_dir / ".env")))
    config_path = Path(env.get("VIDEO2PROMPT_CONFIG_PATH", str(app_support_dir / "config.yaml")))
    return RuntimeFiles(
        resource_root=resource_root,
        app_support_dir=app_support_dir,
        env_path=env_path,
        config_path=config_path,
        exports_dir=app_support_dir / "exports",
        ffprobe_path=Path(
            env.get("VIDEO2PROMPT_FFPROBE_PATH", str(resource_root / "bin" / "ffprobe"))
        ),
        video_prompt_template_path=resource_root / "docs" / "视频复刻提示词.md",
        category_prompt_template_path=resource_root / "docs" / "视频脚本拆解分析.md",
        translation_template_path=resource_root / "docs" / "视频内容审查.md",
        excel_template_path=resource_root / "docs" / "product_prompt_template.xlsx",
    )


def build_config_manager(
    environ: Mapping[str, str] | None = None,
    use_runtime_paths: bool = False,
) -> ConfigManager:
    runtime_files = resolve_runtime_files(environ)
    migrate_legacy_runtime_config(runtime_files)
    runtime_paths = None
    if use_runtime_paths:
        runtime_paths = RuntimePaths(
            resource_root=runtime_files.resource_root,
            app_support_dir=runtime_files.app_support_dir,
            docs_dir=runtime_files.resource_root / "docs",
            data_dir=runtime_files.app_support_dir / "data",
            logs_dir=runtime_files.app_support_dir / "logs",
            exports_dir=runtime_files.exports_dir,
            binaries_dir=runtime_files.resource_root / "bin",
        )
    return ConfigManager(
        env_path=str(runtime_files.env_path),
        config_path=str(runtime_files.config_path),
        runtime_paths=runtime_paths,
    )


def migrate_legacy_runtime_config(runtime_files: RuntimeFiles) -> None:
    config_path = runtime_files.config_path
    if not config_path.exists():
        return

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return

    if not isinstance(data, dict):
        return
    volcengine = data.get("volcengine")
    if not isinstance(volcengine, dict):
        return
    if volcengine.get("model") or "endpoint_id" not in volcengine:
        return

    volcengine["model"] = volcengine.pop("endpoint_id")
    config_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def build_excel_exporter(runtime_files: RuntimeFiles) -> ExcelExporter:
    return ExcelExporter(template_path=str(runtime_files.excel_template_path))


def ensure_exports_dir(runtime_files: RuntimeFiles) -> Path:
    runtime_files.exports_dir.mkdir(parents=True, exist_ok=True)
    return runtime_files.exports_dir


def build_duration_runner(
    parser_client: ParserClient,
    config,
    logger,
    runtime_files: RuntimeFiles,
) -> DurationCheckRunner:
    return DurationCheckRunner(
        parser=parser_client,
        config=config,
        logger=logger,
        ffprobe_path=str(runtime_files.ffprobe_path),
    )


def resolve_runtime_api_key(environ: Mapping[str, str] | None = None) -> str:
    env = environ or os.environ
    return (env.get("VOLCENGINE_API_KEY", "").strip() or env.get("ARK_API_KEY", "").strip())


def resolve_runtime_ai_settings(
    user_state_store: UserStateStore,
    default_model: str,
    environ: Mapping[str, str] | None = None,
) -> ResolvedAiSettings:
    state = user_state_store.load()
    return ResolvedAiSettings(
        api_key=state.volcengine_api_key.strip() or resolve_runtime_api_key(environ),
        model=state.volcengine_model.strip() or (default_model or "").strip(),
    )


def validate_runtime_ai_settings(app_mode: AppMode, api_key: str, model: str) -> str:
    if app_mode == AppMode.DURATION_CHECK:
        return ""
    if not (api_key or "").strip():
        return "缺少 API Key，请先在页面的「AI 配置」中填写 VOLCENGINE_API_KEY"
    if not (model or "").strip():
        return "缺少模型 ID，请先在页面的「AI 配置」中填写模型 ID"
    return ""


def _build_saved_advanced_settings(config: Any) -> dict[str, Any]:
    return {
        "parser.concurrency": int(config.parser.concurrency),
        "volcengine.video_fps": float(config.volcengine.video_fps),
        "volcengine.thinking_type": str(config.volcengine.thinking_type),
        "volcengine.reasoning_effort": str(config.volcengine.reasoning_effort),
    }


def _sync_advanced_settings_widget_state(
    session_state: MutableMapping[str, Any],
    saved_settings: Mapping[str, Any],
) -> None:
    if SESSION_ADVANCED_PARSER_CONCURRENCY not in session_state:
        session_state[SESSION_ADVANCED_PARSER_CONCURRENCY] = int(
            saved_settings["parser.concurrency"]
        )
    if SESSION_ADVANCED_VIDEO_FPS not in session_state:
        session_state[SESSION_ADVANCED_VIDEO_FPS] = float(
            saved_settings["volcengine.video_fps"]
        )
    if SESSION_ADVANCED_THINKING_TYPE not in session_state:
        session_state[SESSION_ADVANCED_THINKING_TYPE] = str(
            saved_settings["volcengine.thinking_type"]
        )
    if SESSION_ADVANCED_REASONING_EFFORT not in session_state:
        session_state[SESSION_ADVANCED_REASONING_EFFORT] = str(
            saved_settings["volcengine.reasoning_effort"]
        )


def _build_advanced_settings_draft(
    app_mode: AppMode,
    session_state: Mapping[str, Any],
) -> dict[str, Any]:
    draft = {
        "parser.concurrency": int(session_state[SESSION_ADVANCED_PARSER_CONCURRENCY]),
    }
    if app_mode != AppMode.DURATION_CHECK:
        draft["volcengine.video_fps"] = float(session_state[SESSION_ADVANCED_VIDEO_FPS])
        draft["volcengine.thinking_type"] = str(
            session_state[SESSION_ADVANCED_THINKING_TYPE]
        )
        draft["volcengine.reasoning_effort"] = str(
            session_state[SESSION_ADVANCED_REASONING_EFFORT]
        )
    return draft


def _advanced_settings_are_synced(
    draft_settings: Mapping[str, Any],
    saved_settings: Mapping[str, Any],
) -> bool:
    return all(saved_settings.get(key) == value for key, value in draft_settings.items())


@st.cache_resource
def _get_run_controller_registry() -> dict[str, RunController]:
    return {}


RUN_CONTROLLER_REGISTRY = _get_run_controller_registry()


def resolve_output_format_for_mode(
    app_mode: AppMode, session_state: MutableMapping[str, Any]
) -> str:
    if app_mode == AppMode.TRANSLATION_COMPLIANCE:
        return OUTPUT_FORMAT_JSON
    return OUTPUT_FORMAT_PLAIN_TEXT


def resolve_mode_prompt(
    app_mode: AppMode,
    session_state: MutableMapping[str, Any],
    video_prompt_default: str,
    category_prompt_default: str,
    translation_prompt_default: str,
) -> str:
    if app_mode == AppMode.TRANSLATION_COMPLIANCE:
        session_key = SESSION_TRANSLATION_COMPLIANCE_PROMPT
    elif app_mode == AppMode.CATEGORY_ANALYSIS:
        session_key = SESSION_CATEGORY_ANALYSIS_PROMPT
    else:
        session_key = SESSION_VIDEO_PROMPT
    prompt = session_state.get(session_key)
    if isinstance(prompt, str):
        return prompt
    if app_mode == AppMode.CATEGORY_ANALYSIS:
        return category_prompt_default
    if app_mode == AppMode.TRANSLATION_COMPLIANCE:
        return translation_prompt_default
    return video_prompt_default


def normalize_runtime_prompt(prompt: str, default_prompt: str) -> str:
    normalized_prompt = (prompt or "").strip()
    return normalized_prompt or default_prompt


def load_prompt_template(path: Path, fallback_text: str) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return fallback_text
    return text or fallback_text


def choose_video_prompt_initial_value(
    saved_prompt: str | None,
    legacy_prompt: str | None,
    default_prompt: str,
    use_saved_prompt: bool,
) -> str:
    if not use_saved_prompt:
        return default_prompt
    return (
        (saved_prompt or "").strip() or (legacy_prompt or "").strip() or default_prompt
    )


def choose_translation_prompt_initial_value(
    saved_prompt: str | None,
    default_prompt: str,
) -> str:
    return (saved_prompt or "").strip() or default_prompt


def choose_category_prompt_initial_value(
    saved_prompt: str | None,
    default_prompt: str,
    use_saved_prompt: bool,
) -> str:
    if not use_saved_prompt:
        return default_prompt
    return (saved_prompt or "").strip() or default_prompt


def is_setting_enabled(value: str | None) -> bool:
    return str(value or "").strip() == "1"


def resolve_prompt_widget_key(app_mode: AppMode) -> str:
    if app_mode == AppMode.TRANSLATION_COMPLIANCE:
        return "translation_compliance_prompt_input"
    if app_mode == AppMode.CATEGORY_ANALYSIS:
        return "category_analysis_prompt_input"
    return "video_prompt_input"


def resolve_prompt_session_key(app_mode: AppMode) -> str:
    if app_mode == AppMode.TRANSLATION_COMPLIANCE:
        return SESSION_TRANSLATION_COMPLIANCE_PROMPT
    if app_mode == AppMode.CATEGORY_ANALYSIS:
        return SESSION_CATEGORY_ANALYSIS_PROMPT
    return SESSION_VIDEO_PROMPT


def should_show_reset_prompt_button(app_mode: AppMode) -> bool:
    return app_mode in {AppMode.VIDEO_PROMPT, AppMode.CATEGORY_ANALYSIS}


def sync_ai_settings_widget_state(
    session_state: MutableMapping[str, Any],
    resolved: ResolvedAiSettings,
    has_saved_ai_settings: bool,
) -> None:
    has_resolution_markers = (
        SESSION_AI_SETTINGS_RESOLVED_API_KEY in session_state
        or SESSION_AI_SETTINGS_RESOLVED_MODEL in session_state
    )
    previous_api_key = str(session_state.get(SESSION_AI_SETTINGS_RESOLVED_API_KEY, ""))
    previous_model = str(session_state.get(SESSION_AI_SETTINGS_RESOLVED_MODEL, ""))
    current_api_key = str(session_state.get("volcengine_api_key_input", ""))
    current_model = str(session_state.get("volcengine_model_input", ""))

    should_reset_legacy_values = not has_saved_ai_settings and not has_resolution_markers
    should_refresh_api_key = (
        "volcengine_api_key_input" not in session_state
        or should_reset_legacy_values
        or (not has_saved_ai_settings and current_api_key == previous_api_key)
    )
    should_refresh_model = (
        "volcengine_model_input" not in session_state
        or should_reset_legacy_values
        or (not has_saved_ai_settings and current_model == previous_model)
    )

    if should_refresh_api_key:
        session_state["volcengine_api_key_input"] = resolved.api_key
    if should_refresh_model:
        session_state["volcengine_model_input"] = resolved.model

    session_state[SESSION_AI_SETTINGS_RESOLVED_API_KEY] = resolved.api_key
    session_state[SESSION_AI_SETTINGS_RESOLVED_MODEL] = resolved.model


def sync_prompt_widget_state(
    app_mode: AppMode,
    session_state: MutableMapping[str, Any],
    video_prompt_default: str,
    category_prompt_default: str,
    translation_prompt_default: str,
) -> str:
    widget_key = resolve_prompt_widget_key(app_mode)
    mode_value = app_mode.value
    last_mode_value = str(session_state.get(SESSION_PROMPT_EDITOR_MODE, ""))
    refresh_mode_value = str(session_state.get(SESSION_PROMPT_EDITOR_REFRESH_MODE, ""))
    if (
        widget_key not in session_state
        or last_mode_value != mode_value
        or refresh_mode_value == mode_value
    ):
        session_state[widget_key] = resolve_mode_prompt(
            app_mode,
            session_state,
            video_prompt_default,
            category_prompt_default,
            translation_prompt_default,
        )
    session_state[SESSION_PROMPT_EDITOR_MODE] = mode_value
    if refresh_mode_value == mode_value:
        session_state.pop(SESSION_PROMPT_EDITOR_REFRESH_MODE, None)
    return widget_key


def resolve_prompt_setting_key(app_mode: AppMode) -> str:
    if app_mode == AppMode.CATEGORY_ANALYSIS:
        return SETTING_CATEGORY_ANALYSIS_PROMPT
    if app_mode == AppMode.TRANSLATION_COMPLIANCE:
        return SETTING_TRANSLATION_COMPLIANCE_PROMPT
    return SETTING_VIDEO_PROMPT


def resolve_prompt_custom_enabled_setting_key(app_mode: AppMode) -> str | None:
    if app_mode == AppMode.CATEGORY_ANALYSIS:
        return SETTING_CATEGORY_ANALYSIS_PROMPT_CUSTOM_ENABLED
    if app_mode == AppMode.VIDEO_PROMPT:
        return SETTING_VIDEO_PROMPT_CUSTOM_ENABLED
    return None


def should_persist_output_format(app_mode: AppMode) -> bool:
    return False


def build_persist_operations(
    app_mode: AppMode,
    prompt_text: str,
    output_format: str,
) -> list[tuple[str, str]]:
    operations = [(resolve_prompt_setting_key(app_mode), prompt_text)]
    custom_enabled_setting_key = resolve_prompt_custom_enabled_setting_key(app_mode)
    if custom_enabled_setting_key:
        operations.append((custom_enabled_setting_key, "1"))
    if should_persist_output_format(app_mode):
        operations.append((SETTING_VIDEO_PROMPT_OUTPUT_FORMAT, output_format))
    return operations


def build_run_settings(
    app_mode: AppMode,
    prompt_text: str,
    video_prompt_default: str,
    category_prompt_default: str,
    translation_prompt_default: str,
    session_state: MutableMapping[str, Any],
) -> ResolvedRunSettings:
    if app_mode == AppMode.TRANSLATION_COMPLIANCE:
        default_prompt = translation_prompt_default
    elif app_mode == AppMode.CATEGORY_ANALYSIS:
        default_prompt = category_prompt_default
    else:
        default_prompt = video_prompt_default
    return ResolvedRunSettings(
        prompt_text=normalize_runtime_prompt(prompt_text, default_prompt),
        output_format=resolve_output_format_for_mode(app_mode, session_state),
    )


def build_controller_payload(
    app_mode: AppMode,
    resolved_settings: ResolvedRunSettings,
) -> dict[str, str]:
    return {
        "app_mode_value": app_mode.value,
        "default_user_prompt": resolved_settings.prompt_text,
        "output_format": resolved_settings.output_format,
    }


def _task_to_row(task: Task) -> dict[str, Any]:
    return {
        "pid": task.pid,
        "原始链接": task.original_link,
        "视频直链": task.video_url,
        "aweme_id": task.aweme_id,
        "状态": task.state.value,
        "解析重试": task.parse_retries,
        "模型重试": task.model_retries,
        "耗时(s)": round(task.duration_seconds, 2),
        "能否翻译": task.can_translate,
        "FPS": task.fps_used,
        "错误": task.error_message,
        "信息摘要预览": task.model_output[:120],
        "缓存命中": task.cache_hit,
        "prompt_tokens": task.model_prompt_tokens,
        "completion_tokens": task.model_completion_tokens,
        "reasoning_tokens": task.model_reasoning_tokens,
        "cached_tokens": task.model_cached_tokens,
        "request_id": task.model_request_id,
        "api_mode": task.model_api_mode,
    }


def _duration_bucket_label(bucket: str) -> str:
    if bucket == "le_15":
        return "<=15s"
    if bucket == "gt_15":
        return ">15s"
    if bucket == "failed":
        return "探测失败"
    return ""


def _rows(
    tasks: list[Task], show_category: bool, show_duration: bool
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        row = _task_to_row(task)
        if show_category:
            row["类目"] = task.category or InputValidator.UNCATEGORIZED
        if show_duration:
            row["视频时长(s)"] = (
                round(float(task.video_duration_seconds), 3)
                if task.video_duration_seconds is not None
                else None
            )
            row["时长分组"] = _duration_bucket_label(task.duration_check_bucket)
        rows.append(row)
    return rows


def _render_table(
    table_placeholder, tasks: list[Task], show_category: bool, show_duration: bool
) -> None:
    table_placeholder.dataframe(
        _rows(tasks, show_category=show_category, show_duration=show_duration),
        width="stretch",
        column_config={
            "原始链接": st.column_config.LinkColumn("原始链接"),
            "视频直链": st.column_config.LinkColumn("视频直链"),
        },
    )


def _count_lines(text: str) -> tuple[int, int]:
    lines = text.splitlines() if text else []
    non_empty = sum(1 for line in lines if line.strip())
    return len(lines), non_empty


async def _run_scheduler(
    config,
    api_key: str,
    default_user_prompt: str,
    output_format: str,
    tasks: list[Task],
    cache: CacheStore,
    logger,
    cancel_event: asyncio.Event,
    on_update=None,
):
    parser_http = httpx.AsyncClient(timeout=config.parser.timeout_seconds)
    model_timeout = config.volcengine.timeout_seconds
    model_http = httpx.AsyncClient(timeout=model_timeout)

    parser_client = ParserClient(
        timeout_seconds=config.parser.timeout_seconds,
        http_client=parser_http,
    )
    volc_files_client = VolcengineFilesClient(
        base_url=config.volcengine.base_url,
        api_key=api_key,
        timeout_seconds=config.volcengine.timeout_seconds,
        http_client=model_http,
    )
    volc_responses_client = VolcengineResponsesClient(
        base_url=config.volcengine.base_url,
        model=config.volcengine.model,
        api_key=api_key,
        timeout_seconds=config.volcengine.timeout_seconds,
        thinking_type=config.volcengine.thinking_type,
        reasoning_effort=config.volcengine.reasoning_effort,
        max_output_tokens=config.volcengine.max_output_tokens,
        stream=config.volcengine.stream,
        http_client=model_http,
    )
    model_client = volc_responses_client

    parser_breaker = CircuitBreaker(
        consecutive_threshold=config.circuit_breaker.parser.consecutive_failures,
        rate_threshold=config.circuit_breaker.parser.failure_rate,
        window_seconds=config.circuit_breaker.window_seconds,
    )
    model_breaker = CircuitBreaker(
        consecutive_threshold=config.circuit_breaker.model.consecutive_failures,
        rate_threshold=config.circuit_breaker.model.failure_rate,
        window_seconds=config.circuit_breaker.window_seconds,
    )

    scheduler = TaskScheduler(
        parser=parser_client,
        model_client=model_client,
        cache=cache,
        config=config,
        parser_breaker=parser_breaker,
        model_breaker=model_breaker,
        logger=logger,
        volcengine_files_client=volc_files_client,
        volcengine_responses_client=volc_responses_client,
    )

    try:
        await scheduler.run(
            tasks=tasks,
            user_prompt=default_user_prompt,
            output_format=output_format,
            on_update=on_update,
            cancel_event=cancel_event,
        )
    finally:
        await parser_http.aclose()
        await model_http.aclose()


async def _run_duration_checker(
    config,
    tasks: list[Task],
    logger,
    runtime_files: RuntimeFiles,
    cancel_event: asyncio.Event,
    on_update=None,
):
    parser_http = httpx.AsyncClient(timeout=config.parser.timeout_seconds)
    parser_client = ParserClient(
        timeout_seconds=config.parser.timeout_seconds,
        http_client=parser_http,
    )
    runner = build_duration_runner(parser_client, config, logger, runtime_files)
    try:
        await runner.run(tasks=tasks, on_update=on_update, cancel_event=cancel_event)
    finally:
        await parser_http.aclose()


def _store_run_controller(
    controller: RunController, session_state: MutableMapping[str, Any] | None = None
) -> str:
    state = st.session_state if session_state is None else session_state
    registry = _get_run_controller_registry()
    previous_id = state.get(SESSION_RUN_CONTROLLER)
    if isinstance(previous_id, str):
        registry.pop(previous_id, None)

    controller_id = uuid4().hex
    registry[controller_id] = controller
    state[SESSION_RUN_CONTROLLER] = controller_id
    return controller_id


def _get_run_controller(
    session_state: MutableMapping[str, Any] | None = None,
) -> RunController | None:
    state = st.session_state if session_state is None else session_state
    controller = state.get(SESSION_RUN_CONTROLLER)
    if isinstance(controller, RunController):
        return controller
    if not isinstance(controller, str):
        return None
    return _get_run_controller_registry().get(controller)


def _clear_run_controller(
    session_state: MutableMapping[str, Any] | None = None,
) -> None:
    state = st.session_state if session_state is None else session_state
    controller_id = state.pop(SESSION_RUN_CONTROLLER, None)
    if isinstance(controller_id, str):
        _get_run_controller_registry().pop(controller_id, None)


def _persist_completed_run_snapshot(
    controller: RunController | None,
    session_state: MutableMapping[str, Any] | None = None,
) -> None:
    if controller is None:
        return

    state = st.session_state if session_state is None else session_state
    state["last_tasks"] = copy.deepcopy(controller.tasks)
    state["last_app_mode"] = controller.app_mode_value
    state["last_default_user_prompt"] = controller.default_user_prompt
    state["last_output_format"] = controller.output_format
    state[SESSION_LAST_RUN_FINISHED] = controller.finished
    state[SESSION_LAST_RUN_CANCELLED] = controller.cancelled or controller.stop_requested
    state[SESSION_LAST_RUN_ERROR_MESSAGE] = controller.error_message


def _sync_run_controller_state(
    controller: RunController | None,
    session_state: MutableMapping[str, Any] | None = None,
) -> bool:
    if controller is None or controller.thread is None:
        return False
    if controller.thread.is_alive():
        return False
    with controller.lock:
        controller.running = False
        controller.finished = True
        controller.loop = None
        controller.cancel_event = None
    _persist_completed_run_snapshot(controller, session_state)
    _clear_run_controller(session_state)
    return True


def _is_run_active(controller: RunController | None) -> bool:
    if controller is None:
        return False
    _sync_run_controller_state(controller)
    with controller.lock:
        return bool(controller.running)


def _request_stop(controller: RunController) -> None:
    with controller.lock:
        controller.stop_requested = True
        loop = controller.loop
        cancel_event = controller.cancel_event
    if loop is not None and cancel_event is not None and not cancel_event.is_set():
        loop.call_soon_threadsafe(cancel_event.set)


def _resolve_completed_run_feedback(
    session_state: MutableMapping[str, Any] | None = None,
) -> tuple[str, str] | None:
    state = st.session_state if session_state is None else session_state
    last_tasks = state.get("last_tasks")
    if not isinstance(last_tasks, list) or not last_tasks:
        return None

    error_message = str(state.get(SESSION_LAST_RUN_ERROR_MESSAGE, "") or "")
    cancelled = bool(state.get(SESSION_LAST_RUN_CANCELLED, False))
    finished = bool(state.get(SESSION_LAST_RUN_FINISHED, False))

    if error_message:
        return ("error", f"任务执行失败: {error_message}")
    if finished and cancelled:
        return ("warning", "任务已停止，未完成任务已标记为已取消")
    if finished:
        return ("success", "任务执行完成")
    return None


def _scheduler_thread_entry(
    controller: RunController,
    config,
    api_key: str,
    default_user_prompt: str,
    output_format: str,
    cache: CacheStore,
    logger,
) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cancel_event = asyncio.Event()
    with controller.lock:
        controller.loop = loop
        controller.cancel_event = cancel_event
        controller.running = True
        controller.finished = False
        controller.error_message = ""

    if controller.stop_requested:
        cancel_event.set()

    try:
        loop.run_until_complete(
            _run_scheduler(
                config=config,
                api_key=api_key,
                default_user_prompt=default_user_prompt,
                output_format=output_format,
                tasks=controller.tasks,
                cache=cache,
                logger=logger,
                cancel_event=cancel_event,
            )
        )
    except BaseException as exc:  # noqa: BLE001
        if not isinstance(exc, asyncio.CancelledError):
            with controller.lock:
                controller.error_message = str(exc)
    finally:
        with controller.lock:
            controller.running = False
            controller.finished = True
            controller.cancelled = cancel_event.is_set()
            controller.loop = None
            controller.cancel_event = None
        with contextlib.suppress(Exception):
            pending = asyncio.all_tasks(loop)
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        loop.close()


def _duration_checker_thread_entry(
    controller: RunController,
    config,
    logger,
    runtime_files: RuntimeFiles,
) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    cancel_event = asyncio.Event()
    with controller.lock:
        controller.loop = loop
        controller.cancel_event = cancel_event
        controller.running = True
        controller.finished = False
        controller.error_message = ""

    if controller.stop_requested:
        cancel_event.set()

    try:
        loop.run_until_complete(
            _run_duration_checker(
                config=config,
                tasks=controller.tasks,
                logger=logger,
                runtime_files=runtime_files,
                cancel_event=cancel_event,
            )
        )
    except BaseException as exc:  # noqa: BLE001
        if not isinstance(exc, asyncio.CancelledError):
            with controller.lock:
                controller.error_message = str(exc)
    finally:
        with controller.lock:
            controller.running = False
            controller.finished = True
            controller.cancelled = cancel_event.is_set()
            controller.loop = None
            controller.cancel_event = None
        with contextlib.suppress(Exception):
            pending = asyncio.all_tasks(loop)
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
        loop.close()


def _resolve_last_mode() -> AppMode:
    last_mode_value = str(
        st.session_state.get("last_app_mode", AppMode.TRANSLATION_COMPLIANCE.value)
    )
    try:
        return AppMode(last_mode_value)
    except ValueError:
        return AppMode.VIDEO_PROMPT


def _normalize_app_mode_session_state(session_state: MutableMapping[Any, Any]) -> str:
    current_mode = str(
        session_state.get("app_mode", AppMode.TRANSLATION_COMPLIANCE.value)
    )
    valid_modes = {mode.value for mode in AppMode}
    if current_mode not in valid_modes:
        current_mode = AppMode.TRANSLATION_COMPLIANCE.value
    session_state["app_mode"] = current_mode
    return current_mode


def _render_runtime_panel(controller: RunController | None) -> None:
    refresh_interval = 1.0 if _is_run_active(controller) else None

    @st.fragment(run_every=refresh_interval)
    def _panel() -> None:
        current_controller = _get_run_controller()
        transitioned = _sync_run_controller_state(current_controller)
        if transitioned:
            st.rerun()

        tasks_to_render = None
        show_category = False
        show_duration = False
        if current_controller is not None and current_controller.tasks:
            tasks_to_render = current_controller.tasks
            show_category = current_controller.show_category
            show_duration = current_controller.is_duration_mode
        elif st.session_state.get("last_tasks"):
            tasks_to_render = st.session_state["last_tasks"]
            last_mode = _resolve_last_mode()
            show_category = last_mode == AppMode.CATEGORY_ANALYSIS
            show_duration = last_mode == AppMode.DURATION_CHECK

        if tasks_to_render:
            _render_table(
                st,
                tasks_to_render,
                show_category=show_category,
                show_duration=show_duration,
            )

        if current_controller is None:
            feedback = _resolve_completed_run_feedback()
            if feedback is None:
                return
            level, message = feedback
            getattr(st, level)(message)
            return

        with current_controller.lock:
            running = current_controller.running
            stop_requested = current_controller.stop_requested
            finished = current_controller.finished
            cancelled = current_controller.cancelled
            error_message = current_controller.error_message

        if running:
            if stop_requested:
                st.warning("停止中，正在取消任务...")
            else:
                st.info("任务执行中...")
            return

        if error_message:
            st.error(f"任务执行失败: {error_message}")
            return

        if finished and (cancelled or stop_requested):
            st.warning("任务已停止，未完成任务已标记为已取消")
            return

        if finished:
            st.success("任务执行完成")

    _panel()


def _visible_tasks_for_cookie_status(controller: RunController | None) -> list[Task]:
    if controller is not None and controller.tasks:
        return controller.tasks
    last_tasks = st.session_state.get("last_tasks")
    if isinstance(last_tasks, list):
        return [task for task in last_tasks if isinstance(task, Task)]
    return []


def _has_cookie_failure(tasks: list[Task]) -> bool:
    return any(COOKIE_RETRY_HINT in (task.error_message or "") for task in tasks)


def _resolve_cookie_failure_state(
    previous_failed: bool, notice: str, tasks: list[Task]
) -> bool:
    if notice in {"saved", "cleared"}:
        return False
    if tasks:
        return _has_cookie_failure(tasks)
    return previous_failed


def _consume_cookie_input_reset(session_state: MutableMapping[str, Any]) -> None:
    if bool(session_state.pop(SESSION_COOKIE_INPUT_RESET, False)):
        session_state["douyin_cookie_input"] = ""


def _consume_ai_settings_input_reset(
    session_state: MutableMapping[str, Any],
    resolved: ResolvedAiSettings,
) -> None:
    if bool(session_state.pop(SESSION_AI_SETTINGS_INPUT_RESET, False)):
        session_state["volcengine_api_key_input"] = resolved.api_key
        session_state["volcengine_model_input"] = resolved.model


def _render_ai_settings_panel(
    user_state_store: UserStateStore,
    default_model: str,
    environ: Mapping[str, str] | None = None,
) -> None:
    notice = str(st.session_state.pop(SESSION_AI_SETTINGS_NOTICE, "") or "")
    resolved = resolve_runtime_ai_settings(
        user_state_store=user_state_store,
        default_model=default_model,
        environ=environ,
    )
    state = user_state_store.load()
    _consume_ai_settings_input_reset(st.session_state, resolved)
    sync_ai_settings_widget_state(
        st.session_state,
        resolved=resolved,
        has_saved_ai_settings=state.has_ai_settings,
    )

    with st.expander("AI 配置", expanded=True):
        if notice == "saved":
            st.success("AI 配置已保存到本机")
        elif notice == "cleared":
            st.info("本地 AI 配置已清空")

        if state.has_ai_settings:
            st.success("状态：已保存本地 AI 配置")
        else:
            st.warning("状态：未保存本地 AI 配置")

        st.text_input(
            "VOLCENGINE_API_KEY",
            key="volcengine_api_key_input",
            type="password",
            placeholder="请输入火山方舟 API Key",
        )
        st.text_input(
            "模型 ID",
            key="volcengine_model_input",
            placeholder="请输入模型 ID",
        )
        save_col, clear_col = st.columns(2)
        with save_col:
            if st.button("保存 AI 配置", use_container_width=True):
                try:
                    user_state_store.save_ai_settings(
                        str(st.session_state.get("volcengine_api_key_input", "")),
                        str(st.session_state.get("volcengine_model_input", "")),
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state[SESSION_AI_SETTINGS_NOTICE] = "saved"
                    st.rerun()
        with clear_col:
            if st.button("清空 AI 配置", use_container_width=True):
                user_state_store.clear_ai_settings()
                st.session_state[SESSION_AI_SETTINGS_INPUT_RESET] = True
                st.session_state[SESSION_AI_SETTINGS_NOTICE] = "cleared"
                st.rerun()


def _render_cookie_panel(user_state_store: UserStateStore, tasks: list[Task]) -> None:
    notice = str(st.session_state.pop(SESSION_COOKIE_NOTICE, "") or "")
    _consume_cookie_input_reset(st.session_state)
    st.session_state[SESSION_COOKIE_FAILURE] = _resolve_cookie_failure_state(
        previous_failed=bool(st.session_state.get(SESSION_COOKIE_FAILURE, False)),
        notice=notice,
        tasks=tasks,
    )

    state = user_state_store.load()
    cookie_failed = bool(st.session_state.get(SESSION_COOKIE_FAILURE, False))

    with st.expander("抖音 Cookie 配置", expanded=True):
        if notice == "saved":
            st.success("Cookie 已保存")
        elif notice == "cleared":
            st.info("Cookie 已清空")

        if not state.has_cookie:
            st.warning("状态：未配置 Cookie")
        elif cookie_failed:
            st.warning("状态：最近一次解析失败，可能已失效")
        else:
            st.success("状态：已保存 Cookie（未验证）")

        st.text_area(
            "手动粘贴抖音 Cookie",
            key="douyin_cookie_input",
            height=120,
            placeholder="请粘贴浏览器里复制出的完整 Cookie 字符串",
        )
        save_col, clear_col = st.columns(2)
        with save_col:
            if st.button("保存 Cookie", use_container_width=True):
                try:
                    user_state_store.save_cookie(
                        str(st.session_state.get("douyin_cookie_input", ""))
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state[SESSION_COOKIE_INPUT_RESET] = True
                    st.session_state[SESSION_COOKIE_NOTICE] = "saved"
                    st.rerun()
        with clear_col:
            if st.button("清空 Cookie", use_container_width=True):
                user_state_store.clear_cookie()
                st.session_state[SESSION_COOKIE_INPUT_RESET] = True
                st.session_state[SESSION_COOKIE_NOTICE] = "cleared"
                st.rerun()

    if cookie_failed:
        st.warning(COOKIE_RETRY_HINT)


def main() -> None:
    st.set_page_config(page_title="video2prompt", layout="wide")
    st.title("video2prompt - 批量视频解读")
    runtime_files = resolve_runtime_files()

    try:
        config_manager = build_config_manager(use_runtime_paths=True)
        base_config = config_manager.get_config()
    except ConfigError as exc:
        st.error(f"配置错误: {exc}")
        st.stop()

    logger = setup_logging(
        base_config.logging.file_path,
        base_config.logging.level,
        base_config.logging.retention_days,
    )
    st.session_state["logger"] = logger

    cache = CacheStore(base_config.cache.db_path)
    asyncio.run(cache.init_db())

    video_prompt_template = load_prompt_template(runtime_files.video_prompt_template_path, "")
    category_prompt_template = load_prompt_template(
        runtime_files.category_prompt_template_path,
        "",
    )
    translation_prompt_template = load_prompt_template(
        runtime_files.translation_template_path,
        DEFAULT_REVIEW_PROMPT,
    )
    if SESSION_VIDEO_PROMPT not in st.session_state:
        video_prompt_custom_enabled = is_setting_enabled(
            asyncio.run(cache.load_setting(SETTING_VIDEO_PROMPT_CUSTOM_ENABLED))
        )
        st.session_state[SESSION_VIDEO_PROMPT] = choose_video_prompt_initial_value(
            asyncio.run(cache.load_setting(SETTING_VIDEO_PROMPT)),
            asyncio.run(cache.load_system_prompt()),
            video_prompt_template,
            video_prompt_custom_enabled,
        )
    if SESSION_TRANSLATION_COMPLIANCE_PROMPT not in st.session_state:
        st.session_state[SESSION_TRANSLATION_COMPLIANCE_PROMPT] = (
            choose_translation_prompt_initial_value(
                asyncio.run(cache.load_setting(SETTING_TRANSLATION_COMPLIANCE_PROMPT)),
                translation_prompt_template,
            )
        )
    if SESSION_CATEGORY_ANALYSIS_PROMPT not in st.session_state:
        category_prompt_custom_enabled = is_setting_enabled(
            asyncio.run(cache.load_setting(SETTING_CATEGORY_ANALYSIS_PROMPT_CUSTOM_ENABLED))
        )
        st.session_state[SESSION_CATEGORY_ANALYSIS_PROMPT] = (
            choose_category_prompt_initial_value(
                asyncio.run(cache.load_setting(SETTING_CATEGORY_ANALYSIS_PROMPT)),
                category_prompt_template,
                category_prompt_custom_enabled,
            )
        )
    if SESSION_VIDEO_PROMPT_OUTPUT_FORMAT not in st.session_state:
        st.session_state[SESSION_VIDEO_PROMPT_OUTPUT_FORMAT] = OUTPUT_FORMAT_PLAIN_TEXT
    if "output_format" not in st.session_state:
        st.session_state["output_format"] = str(
            st.session_state[SESSION_VIDEO_PROMPT_OUTPUT_FORMAT]
        )
    if "app_mode" not in st.session_state:
        st.session_state["app_mode"] = AppMode.TRANSLATION_COMPLIANCE.value
    if SESSION_EXCEL_DOWNLOAD not in st.session_state:
        st.session_state[SESSION_EXCEL_DOWNLOAD] = None
    if SESSION_MARKDOWN_DOWNLOAD not in st.session_state:
        st.session_state[SESSION_MARKDOWN_DOWNLOAD] = None
    if SESSION_DURATION_SHORT_DOWNLOAD not in st.session_state:
        st.session_state[SESSION_DURATION_SHORT_DOWNLOAD] = None
    if SESSION_DURATION_LONG_FAILED_DOWNLOAD not in st.session_state:
        st.session_state[SESSION_DURATION_LONG_FAILED_DOWNLOAD] = None
    if "douyin_cookie_input" not in st.session_state:
        st.session_state["douyin_cookie_input"] = ""
    if SESSION_COOKIE_FAILURE not in st.session_state:
        st.session_state[SESSION_COOKIE_FAILURE] = False

    app_mode_options = [mode.value for mode in AppMode]
    _normalize_app_mode_session_state(st.session_state)
    selected_mode = st.selectbox(
        "运行模式",
        options=app_mode_options,
        key="app_mode",
    )
    app_mode = AppMode(selected_mode)
    st.session_state["output_format"] = resolve_output_format_for_mode(
        app_mode, st.session_state
    )

    user_state_store = UserStateStore()
    run_controller = _get_run_controller()
    _sync_run_controller_state(run_controller)
    _render_cookie_panel(
        user_state_store, _visible_tasks_for_cookie_status(run_controller)
    )
    _render_ai_settings_panel(
        user_state_store=user_state_store,
        default_model=base_config.volcengine.model,
    )

    saved_advanced_settings = _build_saved_advanced_settings(base_config)
    _sync_advanced_settings_widget_state(st.session_state, saved_advanced_settings)
    advanced_settings_notice = str(
        st.session_state.pop(SESSION_ADVANCED_SETTINGS_NOTICE, "") or ""
    )
    current_advanced_draft = _build_advanced_settings_draft(app_mode, st.session_state)
    advanced_settings_synced = _advanced_settings_are_synced(
        current_advanced_draft,
        saved_advanced_settings,
    )

    runtime_overrides: dict[str, Any] = {}
    output_format = OUTPUT_FORMAT_PLAIN_TEXT
    with st.expander("高级设置", expanded=False):
        if advanced_settings_notice:
            st.success(advanced_settings_notice)
        elif advanced_settings_synced:
            st.caption("当前高级设置已同步到配置文件")
        else:
            st.warning("当前高级设置有未保存修改")

        if app_mode == AppMode.DURATION_CHECK:
            st.number_input(
                "解析并发数",
                min_value=1,
                max_value=50,
                step=1,
                key=SESSION_ADVANCED_PARSER_CONCURRENCY,
            )
        elif app_mode == AppMode.TRANSLATION_COMPLIANCE:
            output_format = OUTPUT_FORMAT_JSON
            st.session_state["output_format"] = output_format
            col1, col2 = st.columns(2)
            with col1:
                st.number_input(
                    "解析并发数",
                    min_value=1,
                    max_value=50,
                    step=1,
                    key=SESSION_ADVANCED_PARSER_CONCURRENCY,
                )
                st.number_input(
                    "视频采样帧率",
                    min_value=0.2,
                    max_value=5.0,
                    step=0.1,
                    key=SESSION_ADVANCED_VIDEO_FPS,
                )
            with col2:
                st.selectbox(
                    "思考模式",
                    options=["enabled", "disabled", "auto"],
                    key=SESSION_ADVANCED_THINKING_TYPE,
                )
                st.selectbox(
                    "思考强度",
                    options=["minimal", "low", "medium", "high"],
                    key=SESSION_ADVANCED_REASONING_EFFORT,
                )
        else:
            output_format = OUTPUT_FORMAT_PLAIN_TEXT
            st.session_state["output_format"] = output_format
            st.session_state[SESSION_VIDEO_PROMPT_OUTPUT_FORMAT] = output_format
            col1, col2 = st.columns(2)
            with col1:
                st.number_input(
                    "解析并发数",
                    min_value=1,
                    max_value=50,
                    step=1,
                    key=SESSION_ADVANCED_PARSER_CONCURRENCY,
                )
                st.number_input(
                    "视频采样帧率",
                    min_value=0.2,
                    max_value=5.0,
                    step=0.1,
                    key=SESSION_ADVANCED_VIDEO_FPS,
                )
            with col2:
                st.selectbox(
                    "思考模式",
                    options=["enabled", "disabled", "auto"],
                    key=SESSION_ADVANCED_THINKING_TYPE,
                )
                st.selectbox(
                    "思考强度",
                    options=["minimal", "low", "medium", "high"],
                    key=SESSION_ADVANCED_REASONING_EFFORT,
                )

        current_advanced_draft = _build_advanced_settings_draft(app_mode, st.session_state)
        save_advanced_settings_clicked = st.button("保存高级设置", use_container_width=True)
        if save_advanced_settings_clicked:
            try:
                config_manager.save_mapping(current_advanced_draft)
            except ConfigError as exc:
                st.error(f"高级设置保存失败: {exc}")
            else:
                st.session_state[SESSION_ADVANCED_SETTINGS_NOTICE] = (
                    "高级设置已保存到配置文件"
                )
                st.rerun()

    runtime_overrides.update(current_advanced_draft)

    default_user_prompt = ""
    if app_mode != AppMode.DURATION_CHECK:
        st.subheader("提示词设置")
        prompt_widget_key = sync_prompt_widget_state(
            app_mode,
            st.session_state,
            video_prompt_template,
            category_prompt_template,
            translation_prompt_template,
        )
        prompt_notice = str(st.session_state.pop(SESSION_PROMPT_NOTICE, ""))
        if prompt_notice:
            st.success(prompt_notice)
        default_user_prompt = st.text_area(
            "提示词内容",
            height=180,
            key=prompt_widget_key,
        )
        show_reset_button = should_show_reset_prompt_button(app_mode)
        if show_reset_button:
            save_col, reset_col = st.columns(2)
            with save_col:
                save_clicked = st.button("保存提示词", use_container_width=True)
            with reset_col:
                reset_clicked = st.button("恢复默认提示词", use_container_width=True)
        else:
            save_clicked = st.button("保存提示词")
            reset_clicked = False
        if save_clicked:
            resolved_settings = build_run_settings(
                app_mode,
                default_user_prompt,
                video_prompt_template,
                category_prompt_template,
                translation_prompt_template,
                st.session_state,
            )
            session_prompt_key = resolve_prompt_session_key(app_mode)
            st.session_state[session_prompt_key] = resolved_settings.prompt_text
            st.session_state[SESSION_PROMPT_EDITOR_REFRESH_MODE] = app_mode.value
            for setting_key, setting_value in build_persist_operations(
                app_mode,
                resolved_settings.prompt_text,
                resolved_settings.output_format,
            ):
                asyncio.run(cache.save_setting(setting_key, setting_value))
            st.session_state[SESSION_PROMPT_NOTICE] = "提示词已保存"
            st.rerun()
        if reset_clicked:
            default_prompt = (
                category_prompt_template
                if app_mode == AppMode.CATEGORY_ANALYSIS
                else video_prompt_template
            )
            session_prompt_key = resolve_prompt_session_key(app_mode)
            st.session_state[session_prompt_key] = default_prompt
            st.session_state[SESSION_PROMPT_EDITOR_REFRESH_MODE] = app_mode.value
            operations = [
                (resolve_prompt_setting_key(app_mode), default_prompt),
            ]
            custom_enabled_setting_key = resolve_prompt_custom_enabled_setting_key(app_mode)
            if custom_enabled_setting_key:
                operations.append((custom_enabled_setting_key, "0"))
            for setting_key, setting_value in operations:
                asyncio.run(cache.save_setting(setting_key, setting_value))
            st.session_state[SESSION_PROMPT_NOTICE] = "已恢复默认提示词"
            st.rerun()
    else:
        pass

    category_text = ""
    if app_mode == AppMode.CATEGORY_ANALYSIS:
        pid_col, link_col, category_col = st.columns(3)
        with pid_col:
            pid_text = st.text_area("pid 列表（每行一个）", height=220)
            pid_total, pid_non_empty = _count_lines(pid_text)
            st.caption(f"行数：{pid_total}（非空行：{pid_non_empty}）")
        with link_col:
            link_text = st.text_area("抖音链接列表（每行一个）", height=220)
            link_total, link_non_empty = _count_lines(link_text)
            st.caption(f"行数：{link_total}（非空行：{link_non_empty}）")
        with category_col:
            category_text = st.text_area("类目列表（每行一个）", height=220)
            category_total, category_non_empty = _count_lines(category_text)
            st.caption(f"行数：{category_total}（非空行：{category_non_empty}）")
    else:
        left, right = st.columns(2)
        with left:
            pid_text = st.text_area("pid 列表（每行一个）", height=220)
            pid_total, pid_non_empty = _count_lines(pid_text)
            st.caption(f"行数：{pid_total}（非空行：{pid_non_empty}）")
        with right:
            link_text = st.text_area("抖音链接列表（每行一个）", height=220)
            link_total, link_non_empty = _count_lines(link_text)
            st.caption(f"行数：{link_total}（非空行：{link_non_empty}）")

    is_running = _is_run_active(run_controller)

    start_col, stop_col = st.columns(2)
    with start_col:
        start_clicked = st.button("开始执行", type="primary", disabled=is_running)
    with stop_col:
        stop_clicked = st.button("停止", disabled=not is_running)

    if stop_clicked and run_controller is not None:
        _request_stop(run_controller)
        st.rerun()

    if start_clicked:
        st.session_state[SESSION_EXCEL_DOWNLOAD] = None
        st.session_state[SESSION_MARKDOWN_DOWNLOAD] = None
        st.session_state[SESSION_DURATION_SHORT_DOWNLOAD] = None
        st.session_state[SESSION_DURATION_LONG_FAILED_DOWNLOAD] = None
        pid_lines = pid_text.splitlines()
        link_lines = link_text.splitlines()

        if app_mode == AppMode.CATEGORY_ANALYSIS:
            category_lines = category_text.splitlines()
            validation = InputValidator.validate_line_count_with_category(
                pid_lines, link_lines, category_lines
            )
            inputs: list[TaskInput] = InputValidator.parse_lines_with_category(
                pid_text, link_text, category_text
            )
        else:
            validation = InputValidator.validate_line_count(pid_lines, link_lines)
            inputs = InputValidator.parse_lines(pid_text, link_text)

        if not validation.is_valid:
            st.error(validation.error_message)
            st.stop()

        if not user_state_store.has_cookie():
            st.error(COOKIE_REQUIRED_MESSAGE)
            st.stop()

        invalid = [item for item in inputs if not item.is_valid]
        if invalid:
            st.warning(f"检测到 {len(invalid)} 条无效输入，将跳过处理")
            for item in invalid:
                if app_mode == AppMode.CATEGORY_ANALYSIS:
                    st.write(
                        f"- pid={item.pid or '<空>'} link={item.link or '<空>'} "
                        f"category={item.category or '<空>'} error={item.error}"
                    )
                else:
                    st.write(
                        f"- pid={item.pid or '<空>'} link={item.link or '<空>'} error={item.error}"
                    )

        tasks = [
            Task(pid=item.pid, original_link=item.link, category=item.category)
            for item in inputs
            if item.is_valid
        ]
        if not tasks:
            st.error("没有可执行的有效任务")
            st.stop()

        runtime_ai_settings = ResolvedAiSettings(
            api_key=str(st.session_state.get("volcengine_api_key_input", "")).strip(),
            model=str(st.session_state.get("volcengine_model_input", "")).strip(),
        )
        ai_settings_error = validate_runtime_ai_settings(
            app_mode,
            api_key=runtime_ai_settings.api_key,
            model=runtime_ai_settings.model,
        )
        if ai_settings_error:
            st.error(ai_settings_error)
            st.stop()

        try:
            run_overrides = dict(runtime_overrides)
            if app_mode != AppMode.DURATION_CHECK:
                run_overrides["volcengine.model"] = runtime_ai_settings.model
            config_manager.clear_overrides()
            config_manager.override_mapping(run_overrides)
            runtime_config = config_manager.get_config()
        except Exception as exc:  # noqa: BLE001
            st.error(f"运行时配置无效: {exc}")
            st.stop()

        resolved_settings = build_run_settings(
            app_mode,
            default_user_prompt,
            video_prompt_template,
            category_prompt_template,
            translation_prompt_template,
            st.session_state,
        )
        controller_payload = build_controller_payload(app_mode, resolved_settings)

        controller = RunController(
            tasks=tasks,
            show_category=app_mode == AppMode.CATEGORY_ANALYSIS,
            is_duration_mode=app_mode == AppMode.DURATION_CHECK,
            app_mode_value=controller_payload["app_mode_value"],
            default_user_prompt=controller_payload["default_user_prompt"],
            output_format=controller_payload["output_format"],
            running=True,
            finished=False,
            stop_requested=False,
        )
        if app_mode == AppMode.DURATION_CHECK:
            worker = threading.Thread(
                target=_duration_checker_thread_entry,
                kwargs={
                    "controller": controller,
                    "config": runtime_config,
                    "logger": logger,
                    "runtime_files": runtime_files,
                },
                daemon=True,
            )
        else:
            worker = threading.Thread(
                target=_scheduler_thread_entry,
                kwargs={
                    "controller": controller,
                    "config": runtime_config,
                    "api_key": runtime_ai_settings.api_key,
                    "default_user_prompt": resolved_settings.prompt_text,
                    "output_format": resolved_settings.output_format,
                    "cache": cache,
                    "logger": logger,
                },
                daemon=True,
            )
        controller.thread = worker

        st.session_state["last_tasks"] = []
        _store_run_controller(controller)

        worker.start()
        st.rerun()

    run_controller = _get_run_controller()
    _render_runtime_panel(run_controller)

    run_controller = _get_run_controller()
    _sync_run_controller_state(run_controller)
    if st.session_state.get("last_tasks") and not _is_run_active(run_controller):
        restore_tasks = st.session_state["last_tasks"]
        last_mode = _resolve_last_mode()

        is_category_mode = last_mode == AppMode.CATEGORY_ANALYSIS
        is_duration_mode = last_mode == AppMode.DURATION_CHECK
        if not is_category_mode:
            st.session_state[SESSION_MARKDOWN_DOWNLOAD] = None
        if not is_duration_mode:
            st.session_state[SESSION_DURATION_SHORT_DOWNLOAD] = None
            st.session_state[SESSION_DURATION_LONG_FAILED_DOWNLOAD] = None

        st.subheader("导出结果")
        if is_duration_mode:
            short_col, long_failed_col, tip_col = st.columns([1, 1, 3])
            with tip_col:
                st.info("时长判断模式会生成两份 Excel：<=15s 与 >15s/探测失败")

            with short_col:
                export_duration_clicked = st.button("导出时长结果（双文件）")

            if export_duration_clicked:
                exporter = DurationExcelExporter()
                output_dir = ensure_exports_dir(runtime_files)
                short_name, long_failed_name = exporter.generate_filenames()
                short_file = output_dir / short_name
                long_failed_file = output_dir / long_failed_name
                exporter.export_dual(
                    tasks=restore_tasks,
                    short_output_path=str(short_file),
                    long_failed_output_path=str(long_failed_file),
                )
                st.session_state[SESSION_DURATION_SHORT_DOWNLOAD] = {
                    "data": short_file.read_bytes(),
                    "file_name": short_file.name,
                    "path": str(short_file.resolve()),
                }
                st.session_state[SESSION_DURATION_LONG_FAILED_DOWNLOAD] = {
                    "data": long_failed_file.read_bytes(),
                    "file_name": long_failed_file.name,
                    "path": str(long_failed_file.resolve()),
                }
                st.success(f"导出成功: {short_file.name}，{long_failed_file.name}")

            short_payload = st.session_state.get(SESSION_DURATION_SHORT_DOWNLOAD)
            if short_payload:
                short_key_suffix = hashlib.sha1(short_payload["data"]).hexdigest()[:12]
                with short_col:
                    st.download_button(
                        label="下载 <=15s Excel",
                        data=short_payload["data"],
                        file_name=short_payload["file_name"],
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        on_click="ignore",
                        key=f"download_duration_short_{short_key_suffix}",
                    )
                st.caption(f"下载失败可直接使用本地文件：`{short_payload['path']}`")

            long_failed_payload = st.session_state.get(
                SESSION_DURATION_LONG_FAILED_DOWNLOAD
            )
            if long_failed_payload:
                long_key_suffix = hashlib.sha1(long_failed_payload["data"]).hexdigest()[
                    :12
                ]
                with long_failed_col:
                    st.download_button(
                        label="下载 >15s/失败 Excel",
                        data=long_failed_payload["data"],
                        file_name=long_failed_payload["file_name"],
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        on_click="ignore",
                        key=f"download_duration_long_failed_{long_key_suffix}",
                    )
                st.caption(
                    f"下载失败可直接使用本地文件：`{long_failed_payload['path']}`"
                )
        elif is_category_mode:
            excel_col, markdown_col, tip_col = st.columns([1, 1, 3])
            with tip_col:
                st.info(
                    "请尽快导出结果查看完整提示词，避免刷新后结果丢失，导出的 Excel 可直接导入 Lumen"
                )

            with excel_col:
                export_excel_clicked = st.button("导出 Excel")
            with markdown_col:
                export_markdown_clicked = st.button("导出 Markdown（按类目）")

            if export_excel_clicked:
                exporter = build_excel_exporter(runtime_files)
                output_dir = ensure_exports_dir(runtime_files)
                output_file = output_dir / ExcelExporter.generate_filename()
                exporter.export(
                    tasks=restore_tasks,
                    output_path=str(output_file),
                    include_category=True,
                )
                st.session_state[SESSION_EXCEL_DOWNLOAD] = {
                    "data": output_file.read_bytes(),
                    "file_name": output_file.name,
                    "path": str(output_file.resolve()),
                }
                st.success(f"导出成功: {output_file}")

            if export_markdown_clicked:
                markdown_exporter = MarkdownExporter(output_root=str(ensure_exports_dir(runtime_files)))
                try:
                    result = markdown_exporter.export_by_category(tasks=restore_tasks)
                except ValueError as exc:
                    st.session_state[SESSION_MARKDOWN_DOWNLOAD] = None
                    st.warning(str(exc))
                else:
                    st.session_state[SESSION_MARKDOWN_DOWNLOAD] = {
                        "data": result.zip_path.read_bytes(),
                        "file_name": result.zip_path.name,
                        "path": str(result.zip_path.resolve()),
                    }
                    st.success(
                        f"Markdown 导出成功：{result.exported_category_count} 个类目，"
                        f"{result.exported_task_count} 条视频脚本"
                    )

            excel_download_payload = st.session_state.get(SESSION_EXCEL_DOWNLOAD)
            if excel_download_payload:
                excel_key_suffix = hashlib.sha1(
                    excel_download_payload["data"]
                ).hexdigest()[:12]
                with excel_col:
                    st.download_button(
                        label="下载 Excel",
                        data=excel_download_payload["data"],
                        file_name=excel_download_payload["file_name"],
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        on_click="ignore",
                        key=f"download_excel_file_{excel_key_suffix}",
                    )
                st.caption(
                    f"下载失败可直接使用本地文件：`{excel_download_payload['path']}`"
                )

            markdown_download_payload = st.session_state.get(SESSION_MARKDOWN_DOWNLOAD)
            if markdown_download_payload:
                markdown_key_suffix = hashlib.sha1(
                    markdown_download_payload["data"]
                ).hexdigest()[:12]
                with markdown_col:
                    st.download_button(
                        label="下载 Markdown ZIP",
                        data=markdown_download_payload["data"],
                        file_name=markdown_download_payload["file_name"],
                        mime="application/zip",
                        on_click="ignore",
                        key=f"download_markdown_zip_{markdown_key_suffix}",
                    )
                st.caption(
                    f"下载失败可直接使用本地文件：`{markdown_download_payload['path']}`"
                )
        else:
            excel_col, tip_col = st.columns([1, 3])
            with tip_col:
                st.info(
                    "请尽快导出结果查看完整提示词，避免刷新后结果丢失，导出的 Excel 可直接导入 Lumen"
                )

            with excel_col:
                export_excel_clicked = st.button("导出 Excel")

            if export_excel_clicked:
                exporter = build_excel_exporter(runtime_files)
                output_dir = ensure_exports_dir(runtime_files)
                output_file = output_dir / ExcelExporter.generate_filename()
                exporter.export(
                    tasks=restore_tasks,
                    output_path=str(output_file),
                    include_category=False,
                )
                st.session_state[SESSION_EXCEL_DOWNLOAD] = {
                    "data": output_file.read_bytes(),
                    "file_name": output_file.name,
                    "path": str(output_file.resolve()),
                }
                st.success(f"导出成功: {output_file}")

            excel_download_payload = st.session_state.get(SESSION_EXCEL_DOWNLOAD)
            if excel_download_payload:
                excel_key_suffix = hashlib.sha1(
                    excel_download_payload["data"]
                ).hexdigest()[:12]
                with excel_col:
                    st.download_button(
                        label="下载 Excel",
                        data=excel_download_payload["data"],
                        file_name=excel_download_payload["file_name"],
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        on_click="ignore",
                        key=f"download_excel_file_{excel_key_suffix}",
                    )
                st.caption(
                    f"下载失败可直接使用本地文件：`{excel_download_payload['path']}`"
                )


if __name__ == "__main__":
    main()
