"""Streamlit 入口。"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, MutableMapping

import httpx
import streamlit as st

from video2prompt.cache_store import CacheStore
from video2prompt.circuit_breaker import CircuitBreaker
from video2prompt.config import ConfigManager
from video2prompt.duration_check_runner import DurationCheckRunner
from video2prompt.duration_excel_exporter import DurationExcelExporter
from video2prompt.errors import ConfigError
from video2prompt.excel_exporter import ExcelExporter
from video2prompt.gemini_client import GeminiClient
from video2prompt.logging_utils import setup_logging
from video2prompt.markdown_exporter import MarkdownExporter
from video2prompt.models import AppMode, Task, TaskInput
from video2prompt.parser_client import COOKIE_REQUIRED_MESSAGE, COOKIE_RETRY_HINT, ParserClient
from video2prompt.review_result import DEFAULT_REVIEW_PROMPT
from video2prompt.task_scheduler import TaskScheduler
from video2prompt.user_state_store import UserStateStore
from video2prompt.validator import InputValidator
from video2prompt.volcengine_batch_client import VolcengineBatchClient
from video2prompt.volcengine_client import VolcengineClient
from video2prompt.volcengine_files_client import VolcengineFilesClient
from video2prompt.volcengine_responses_client import VolcengineResponsesClient

OUTPUT_FORMAT_PLAIN_TEXT = "plain_text"
OUTPUT_FORMAT_JSON = "json"
OUTPUT_FORMAT_LABEL_TO_VALUE = {
    "纯文本（默认）": OUTPUT_FORMAT_PLAIN_TEXT,
    "JSON": OUTPUT_FORMAT_JSON,
}
OUTPUT_FORMAT_VALUE_TO_LABEL = {value: label for label, value in OUTPUT_FORMAT_LABEL_TO_VALUE.items()}
SESSION_EXCEL_DOWNLOAD = "excel_download_payload"
SESSION_MARKDOWN_DOWNLOAD = "markdown_download_payload"
SESSION_DURATION_SHORT_DOWNLOAD = "duration_short_download_payload"
SESSION_DURATION_LONG_FAILED_DOWNLOAD = "duration_long_failed_download_payload"
SESSION_RUN_CONTROLLER = "run_controller"
SESSION_COOKIE_NOTICE = "cookie_notice"
SESSION_COOKIE_FAILURE = "cookie_failure"
SESSION_COOKIE_INPUT_RESET = "cookie_input_reset"


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


def _task_to_row(task: Task) -> dict[str, Any]:
    return {
        "pid": task.pid,
        "原始链接": task.original_link,
        "视频直链": task.video_url,
        "aweme_id": task.aweme_id,
        "状态": task.state.value,
        "解析重试": task.parse_retries,
        "模型重试": task.gemini_retries,
        "耗时(s)": round(task.duration_seconds, 2),
        "能否翻译": task.can_translate,
        "FPS": task.fps_used,
        "错误": task.error_message,
        "信息摘要预览": task.gemini_output[:120],
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


def _rows(tasks: list[Task], show_category: bool, show_duration: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        row = _task_to_row(task)
        if show_category:
            row["类目"] = task.category or InputValidator.UNCATEGORIZED
        if show_duration:
            row["视频时长(s)"] = (
                round(float(task.video_duration_seconds), 3) if task.video_duration_seconds is not None else None
            )
            row["时长分组"] = _duration_bucket_label(task.duration_check_bucket)
        rows.append(row)
    return rows


def _render_table(table_placeholder, tasks: list[Task], show_category: bool, show_duration: bool) -> None:
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
    model_timeout = config.gemini.timeout_seconds if config.provider == "gemini" else config.volcengine.timeout_seconds
    model_http = httpx.AsyncClient(timeout=model_timeout)
    volc_files_client = None
    volc_responses_client = None
    volc_batch_client = None

    parser_client = ParserClient(
        timeout_seconds=config.parser.timeout_seconds,
        http_client=parser_http,
    )
    if config.provider == "gemini":
        model_client = GeminiClient(
            base_url=config.gemini.base_url,
            model=config.gemini.model,
            api_key=api_key,
            timeout_seconds=config.gemini.timeout_seconds,
            thinking_level=config.gemini.thinking_level,
            media_resolution=config.gemini.media_resolution,
            http_client=model_http,
        )
    elif config.provider == "volcengine":
        model_client = VolcengineClient(
            base_url=config.volcengine.base_url,
            endpoint_id=config.volcengine.endpoint_id,
            target_model=config.volcengine.target_model,
            api_key=api_key,
            timeout_seconds=config.volcengine.timeout_seconds,
            thinking_type=config.volcengine.thinking_type,
            reasoning_effort=config.volcengine.reasoning_effort,
            max_completion_tokens=config.volcengine.max_completion_tokens,
            stream_usage=config.volcengine.stream_usage,
            http_client=model_http,
        )
        volc_files_client = VolcengineFilesClient(
            base_url=config.volcengine.base_url,
            api_key=api_key,
            timeout_seconds=config.volcengine.timeout_seconds,
            http_client=model_http,
        )
        volc_responses_client = VolcengineResponsesClient(
            base_url=config.volcengine.base_url,
            endpoint_id=config.volcengine.endpoint_id,
            api_key=api_key,
            timeout_seconds=config.volcengine.timeout_seconds,
            thinking_type=config.volcengine.thinking_type,
            reasoning_effort=config.volcengine.reasoning_effort,
            max_completion_tokens=config.volcengine.max_completion_tokens,
            http_client=model_http,
        )
        volc_batch_client = VolcengineBatchClient(
            base_url=config.volcengine.base_url,
            endpoint_id=config.volcengine.endpoint_id,
            api_key=api_key,
            timeout_seconds=config.volcengine.timeout_seconds,
            thinking_type=config.volcengine.thinking_type,
            reasoning_effort=config.volcengine.reasoning_effort,
            max_completion_tokens=config.volcengine.max_completion_tokens,
            http_client=model_http,
        )
    else:
        raise ConfigError(f"不支持的 provider: {config.provider}")

    parser_breaker = CircuitBreaker(
        consecutive_threshold=config.circuit_breaker.parser.consecutive_failures,
        rate_threshold=config.circuit_breaker.parser.failure_rate,
        window_seconds=config.circuit_breaker.window_seconds,
    )
    gemini_breaker = CircuitBreaker(
        consecutive_threshold=config.circuit_breaker.gemini.consecutive_failures,
        rate_threshold=config.circuit_breaker.gemini.failure_rate,
        window_seconds=config.circuit_breaker.window_seconds,
    )

    scheduler = TaskScheduler(
        parser=parser_client,
        model_client=model_client,
        cache=cache,
        config=config,
        parser_breaker=parser_breaker,
        gemini_breaker=gemini_breaker,
        logger=logger,
        volcengine_files_client=volc_files_client,
        volcengine_responses_client=volc_responses_client,
        volcengine_batch_client=volc_batch_client,
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
    cancel_event: asyncio.Event,
    on_update=None,
):
    parser_http = httpx.AsyncClient(timeout=config.parser.timeout_seconds)
    parser_client = ParserClient(
        timeout_seconds=config.parser.timeout_seconds,
        http_client=parser_http,
    )
    runner = DurationCheckRunner(
        parser=parser_client,
        config=config,
        logger=logger,
    )
    try:
        await runner.run(tasks=tasks, on_update=on_update, cancel_event=cancel_event)
    finally:
        await parser_http.aclose()


def _get_run_controller() -> RunController | None:
    controller = st.session_state.get(SESSION_RUN_CONTROLLER)
    if isinstance(controller, RunController):
        return controller
    return None


def _sync_run_controller_state(controller: RunController | None) -> None:
    if controller is None or controller.thread is None:
        return
    if controller.thread.is_alive():
        return
    with controller.lock:
        controller.running = False
        controller.finished = True
        controller.loop = None
        controller.cancel_event = None


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
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


def _duration_checker_thread_entry(
    controller: RunController,
    config,
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
            _run_duration_checker(
                config=config,
                tasks=controller.tasks,
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
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


def _resolve_last_mode() -> AppMode:
    last_mode_value = str(st.session_state.get("last_app_mode", AppMode.VIDEO_PROMPT.value))
    try:
        return AppMode(last_mode_value)
    except ValueError:
        return AppMode.VIDEO_PROMPT


def _render_runtime_panel(controller: RunController | None) -> None:
    refresh_interval = 1.0 if _is_run_active(controller) else None

    @st.fragment(run_every=refresh_interval)
    def _panel() -> None:
        current_controller = _get_run_controller()
        _sync_run_controller_state(current_controller)

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
            _render_table(st, tasks_to_render, show_category=show_category, show_duration=show_duration)

        if current_controller is None:
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


def _resolve_cookie_failure_state(previous_failed: bool, notice: str, tasks: list[Task]) -> bool:
    if notice in {"saved", "cleared"}:
        return False
    if tasks:
        return _has_cookie_failure(tasks)
    return previous_failed


def _consume_cookie_input_reset(session_state: MutableMapping[str, Any]) -> None:
    if bool(session_state.pop(SESSION_COOKIE_INPUT_RESET, False)):
        session_state["douyin_cookie_input"] = ""


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

        st.caption(f"本地保存位置：{user_state_store.path}")
        st.caption("Cookie 仅保存在当前用户目录，不会写回 config.yaml，也不会写入 SQLite 缓存。")
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
                    user_state_store.save_cookie(str(st.session_state.get("douyin_cookie_input", "")))
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

    try:
        config_manager = ConfigManager(env_path=".env", config_path="config.yaml")
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

    if "default_user_prompt" not in st.session_state:
        saved_prompt = asyncio.run(cache.load_system_prompt())
        st.session_state["default_user_prompt"] = saved_prompt or DEFAULT_REVIEW_PROMPT
    if "output_format" not in st.session_state:
        st.session_state["output_format"] = OUTPUT_FORMAT_PLAIN_TEXT
    if "app_mode" not in st.session_state:
        st.session_state["app_mode"] = AppMode.VIDEO_PROMPT.value
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

    if base_config.provider == "gemini":
        st.caption(f"当前模型服务商：gemini（model={base_config.gemini.model}）")
    else:
        st.caption(
            "当前模型服务商：volcengine "
            f"（endpoint_id={base_config.volcengine.endpoint_id}，target_model={base_config.volcengine.target_model}）"
        )

    app_mode_options = [mode.value for mode in AppMode]
    current_mode = str(st.session_state.get("app_mode", AppMode.VIDEO_PROMPT.value))
    if current_mode not in app_mode_options:
        current_mode = AppMode.VIDEO_PROMPT.value
    selected_mode = st.selectbox(
        "运行模式",
        options=app_mode_options,
        index=app_mode_options.index(current_mode),
    )
    st.session_state["app_mode"] = selected_mode
    app_mode = AppMode(selected_mode)

    user_state_store = UserStateStore()
    run_controller = _get_run_controller()
    _sync_run_controller_state(run_controller)
    _render_cookie_panel(user_state_store, _visible_tasks_for_cookie_status(run_controller))

    runtime_overrides: dict[str, Any] = {}
    output_format = OUTPUT_FORMAT_PLAIN_TEXT
    with st.expander("运行时配置覆盖（仅本次运行生效，不写回 config.yaml）", expanded=False):
        st.caption("页面仅保留常用运行参数；退避、熔断、批量 Chat、完成后等待等高级项请在 config.yaml 中调整。")
        if app_mode == AppMode.DURATION_CHECK:
            st.caption("时长判断模式仅使用解析与时长探测，不会调用模型。")
            runtime_overrides["parser.concurrency"] = st.number_input(
                "解析并发数（parser.concurrency）",
                min_value=1,
                max_value=50,
                value=base_config.parser.concurrency,
                step=1,
            )
        else:
            current_output_format = str(st.session_state.get("output_format", OUTPUT_FORMAT_PLAIN_TEXT))
            current_output_label = OUTPUT_FORMAT_VALUE_TO_LABEL.get(current_output_format, "纯文本（默认）")
            output_format_label = st.selectbox(
                "输出格式",
                options=list(OUTPUT_FORMAT_LABEL_TO_VALUE.keys()),
                index=list(OUTPUT_FORMAT_LABEL_TO_VALUE.keys()).index(current_output_label),
                help="纯文本会保留模型原始输出；JSON 会按现有规则解析为“能否翻译+信息摘要”。",
            )
            output_format = OUTPUT_FORMAT_LABEL_TO_VALUE[output_format_label]
            st.session_state["output_format"] = output_format
            if base_config.provider == "gemini":
                col1, col2 = st.columns(2)
                with col1:
                    runtime_overrides["parser.concurrency"] = st.number_input(
                        "解析并发数（parser.concurrency）",
                        min_value=1,
                        max_value=50,
                        value=base_config.parser.concurrency,
                        step=1,
                    )
                with col2:
                    runtime_overrides["gemini.video_fps"] = st.number_input(
                        "模型视频采样帧率（gemini.video_fps）",
                        min_value=0.1,
                        max_value=20.0,
                        value=float(base_config.gemini.video_fps),
                        step=0.1,
                    )
            else:
                col1, col2 = st.columns(2)
                with col1:
                    runtime_overrides["parser.concurrency"] = st.number_input(
                        "解析并发数（parser.concurrency）",
                        min_value=1,
                        max_value=50,
                        value=base_config.parser.concurrency,
                        step=1,
                    )
                    runtime_overrides["volcengine.video_fps"] = st.number_input(
                        "模型视频采样帧率（volcengine.video_fps）",
                        min_value=0.2,
                        max_value=5.0,
                        value=float(base_config.volcengine.video_fps),
                        step=0.1,
                    )
                with col2:
                    thinking_options = ["enabled", "disabled", "auto"]
                    current_thinking = (base_config.volcengine.thinking_type or "enabled").strip().lower()
                    if current_thinking not in thinking_options:
                        current_thinking = "enabled"
                    runtime_overrides["volcengine.thinking_type"] = st.selectbox(
                        "思考模式（volcengine.thinking_type）",
                        options=thinking_options,
                        index=thinking_options.index(current_thinking),
                    )
                    reasoning_options = ["minimal", "low", "medium", "high"]
                    current_reasoning = (base_config.volcengine.reasoning_effort or "medium").strip().lower()
                    if current_reasoning not in reasoning_options:
                        current_reasoning = "medium"
                    runtime_overrides["volcengine.reasoning_effort"] = st.selectbox(
                        "思考强度（volcengine.reasoning_effort）",
                        options=reasoning_options,
                        index=reasoning_options.index(current_reasoning),
                    )

    default_user_prompt = ""
    if app_mode != AppMode.DURATION_CHECK:
        st.subheader("视频解析提示词配置")
        default_user_prompt = st.text_area(
            "DEFAULT_USER_PROMPT",
            value=st.session_state["default_user_prompt"],
            height=180,
        )
        if st.button("保存 DEFAULT_USER_PROMPT"):
            asyncio.run(cache.save_system_prompt(default_user_prompt or ""))
            st.session_state["default_user_prompt"] = default_user_prompt or ""
            st.success("DEFAULT_USER_PROMPT 已保存")
    else:
        st.caption("当前模式不使用模型提示词。")

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
            validation = InputValidator.validate_line_count_with_category(pid_lines, link_lines, category_lines)
            inputs: list[TaskInput] = InputValidator.parse_lines_with_category(pid_text, link_text, category_text)
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
                    st.write(f"- pid={item.pid or '<空>'} link={item.link or '<空>'} error={item.error}")

        tasks = [Task(pid=item.pid, original_link=item.link, category=item.category) for item in inputs if item.is_valid]
        if not tasks:
            st.error("没有可执行的有效任务")
            st.stop()

        try:
            config_manager.clear_overrides()
            config_manager.override_mapping(runtime_overrides)
            runtime_config = config_manager.get_config()
        except Exception as exc:  # noqa: BLE001
            st.error(f"运行时配置无效: {exc}")
            st.stop()

        controller = RunController(
            tasks=tasks,
            show_category=app_mode == AppMode.CATEGORY_ANALYSIS,
            is_duration_mode=app_mode == AppMode.DURATION_CHECK,
            app_mode_value=app_mode.value,
            default_user_prompt=default_user_prompt or "",
            output_format=output_format,
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
                },
                daemon=True,
            )
        else:
            try:
                api_key = config_manager.get_provider_api_key()
            except ConfigError as exc:
                st.error(f"配置错误: {exc}")
                st.stop()
            worker = threading.Thread(
                target=_scheduler_thread_entry,
                kwargs={
                    "controller": controller,
                    "config": runtime_config,
                    "api_key": api_key,
                    "default_user_prompt": default_user_prompt or "",
                    "output_format": output_format,
                    "cache": cache,
                    "logger": logger,
                },
                daemon=True,
            )
        controller.thread = worker

        st.session_state["last_tasks"] = tasks
        st.session_state["last_app_mode"] = app_mode.value
        st.session_state["last_default_user_prompt"] = default_user_prompt
        st.session_state["last_output_format"] = output_format
        st.session_state[SESSION_RUN_CONTROLLER] = controller

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
                output_dir = Path("exports")
                output_dir.mkdir(parents=True, exist_ok=True)
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

            long_failed_payload = st.session_state.get(SESSION_DURATION_LONG_FAILED_DOWNLOAD)
            if long_failed_payload:
                long_key_suffix = hashlib.sha1(long_failed_payload["data"]).hexdigest()[:12]
                with long_failed_col:
                    st.download_button(
                        label="下载 >15s/失败 Excel",
                        data=long_failed_payload["data"],
                        file_name=long_failed_payload["file_name"],
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        on_click="ignore",
                        key=f"download_duration_long_failed_{long_key_suffix}",
                    )
                st.caption(f"下载失败可直接使用本地文件：`{long_failed_payload['path']}`")
        elif is_category_mode:
            excel_col, markdown_col, tip_col = st.columns([1, 1, 3])
            with tip_col:
                st.info("请尽快导出结果查看完整提示词，避免刷新后结果丢失，导出的 Excel 可直接导入 Lumen")

            with excel_col:
                export_excel_clicked = st.button("导出 Excel")
            with markdown_col:
                export_markdown_clicked = st.button("导出 Markdown（按类目）")

            if export_excel_clicked:
                exporter = ExcelExporter(template_path="docs/product_prompt_template.xlsx")
                output_dir = Path("exports")
                output_dir.mkdir(parents=True, exist_ok=True)
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
                markdown_exporter = MarkdownExporter(output_root="exports")
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
                excel_key_suffix = hashlib.sha1(excel_download_payload["data"]).hexdigest()[:12]
                with excel_col:
                    st.download_button(
                        label="下载 Excel",
                        data=excel_download_payload["data"],
                        file_name=excel_download_payload["file_name"],
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        on_click="ignore",
                        key=f"download_excel_file_{excel_key_suffix}",
                    )
                st.caption(f"下载失败可直接使用本地文件：`{excel_download_payload['path']}`")

            markdown_download_payload = st.session_state.get(SESSION_MARKDOWN_DOWNLOAD)
            if markdown_download_payload:
                markdown_key_suffix = hashlib.sha1(markdown_download_payload["data"]).hexdigest()[:12]
                with markdown_col:
                    st.download_button(
                        label="下载 Markdown ZIP",
                        data=markdown_download_payload["data"],
                        file_name=markdown_download_payload["file_name"],
                        mime="application/zip",
                        on_click="ignore",
                        key=f"download_markdown_zip_{markdown_key_suffix}",
                    )
                st.caption(f"下载失败可直接使用本地文件：`{markdown_download_payload['path']}`")
        else:
            excel_col, tip_col = st.columns([1, 3])
            with tip_col:
                st.info("请尽快导出结果查看完整提示词，避免刷新后结果丢失，导出的 Excel 可直接导入 Lumen")

            with excel_col:
                export_excel_clicked = st.button("导出 Excel")

            if export_excel_clicked:
                exporter = ExcelExporter(template_path="docs/product_prompt_template.xlsx")
                output_dir = Path("exports")
                output_dir.mkdir(parents=True, exist_ok=True)
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
                excel_key_suffix = hashlib.sha1(excel_download_payload["data"]).hexdigest()[:12]
                with excel_col:
                    st.download_button(
                        label="下载 Excel",
                        data=excel_download_payload["data"],
                        file_name=excel_download_payload["file_name"],
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        on_click="ignore",
                        key=f"download_excel_file_{excel_key_suffix}",
                    )
                st.caption(f"下载失败可直接使用本地文件：`{excel_download_payload['path']}`")


if __name__ == "__main__":
    main()
