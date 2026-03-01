"""Streamlit 入口。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import streamlit as st

from video2prompt.cache_store import CacheStore
from video2prompt.circuit_breaker import CircuitBreaker
from video2prompt.config import ConfigManager
from video2prompt.errors import ConfigError
from video2prompt.excel_exporter import ExcelExporter
from video2prompt.gemini_client import GeminiClient
from video2prompt.logging_utils import setup_logging
from video2prompt.markdown_exporter import MarkdownExporter
from video2prompt.models import AppMode, Task, TaskInput
from video2prompt.parser_client import ParserClient
from video2prompt.review_result import DEFAULT_REVIEW_PROMPT
from video2prompt.task_scheduler import TaskScheduler
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


def _rows(tasks: list[Task], show_category: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        row = _task_to_row(task)
        if show_category:
            row["类目"] = task.category or InputValidator.UNCATEGORIZED
        rows.append(row)
    return rows


def _render_table(table_placeholder, tasks: list[Task], show_category: bool) -> None:
    table_placeholder.dataframe(
        _rows(tasks, show_category=show_category),
        width="stretch",
        column_config={
            "原始链接": st.column_config.LinkColumn("原始链接"),
            "视频直链": st.column_config.LinkColumn("视频直链"),
        },
    )


def _parse_backoff(value: str) -> list[int]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    return [int(item) for item in items]


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
    show_category: bool,
    cache: CacheStore,
    table_placeholder,
    status_placeholder,
):
    parser_http = httpx.AsyncClient(timeout=config.parser.timeout_seconds)
    model_timeout = config.gemini.timeout_seconds if config.provider == "gemini" else config.volcengine.timeout_seconds
    model_http = httpx.AsyncClient(timeout=model_timeout)
    volc_files_client = None
    volc_responses_client = None
    volc_batch_client = None

    parser_client = ParserClient(
        base_url=config.parser.base_url,
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
        logger=st.session_state["logger"],
        volcengine_files_client=volc_files_client,
        volcengine_responses_client=volc_responses_client,
        volcengine_batch_client=volc_batch_client,
    )

    cancel_event = asyncio.Event()

    def on_update(_: Task) -> None:
        _render_table(table_placeholder, tasks, show_category=show_category)

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


def main() -> None:
    st.set_page_config(page_title="video2prompt", layout="wide")
    st.title("video2prompt - 批量视频解读")

    try:
        config_manager = ConfigManager(env_path=".env", config_path="config.yaml")
        base_config = config_manager.get_config()
        api_key = config_manager.get_provider_api_key()
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

    with st.expander("服务状态", expanded=True):
        checker = ParserClient(base_url=base_config.parser.base_url, timeout_seconds=5)
        ok, msg = asyncio.run(checker.health_check())
        if ok:
            st.success(msg)
        else:
            st.warning(msg)

    with st.expander("运行时配置覆盖（仅本次运行生效，不写回 config.yaml）", expanded=False):
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
        col1, col2, col3 = st.columns(3)
        runtime_overrides: dict[str, Any] = {}
        volc_max_tokens_text = ""
        with col1:
            runtime_overrides["parser.concurrency"] = st.number_input(
                "解析并发数（parser.concurrency）",
                min_value=1,
                max_value=5,
                value=base_config.parser.concurrency,
                step=1,
            )
            if base_config.provider == "gemini":
                runtime_overrides["gemini.video_fps"] = st.number_input(
                    "模型视频采样帧率（gemini.video_fps）",
                    min_value=0.1,
                    max_value=20.0,
                    value=float(base_config.gemini.video_fps),
                    step=0.1,
                )
            else:
                runtime_overrides["volcengine.video_fps"] = st.number_input(
                    "模型视频采样帧率（volcengine.video_fps）",
                    min_value=0.2,
                    max_value=5.0,
                    value=float(base_config.volcengine.video_fps),
                    step=0.1,
                )
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
                volc_max_tokens_text = st.text_input(
                    "最大输出 token（volcengine.max_completion_tokens，留空不下发）",
                    value=(
                        ""
                        if base_config.volcengine.max_completion_tokens is None
                        else str(base_config.volcengine.max_completion_tokens)
                    ),
                )
        with col2:
            runtime_overrides["parser.pre_delay_min_seconds"] = st.number_input(
                "解析前最小等待秒数（parser.pre_delay_min_seconds）",
                min_value=0.0,
                value=float(base_config.parser.pre_delay_min_seconds),
                step=0.1,
            )
            runtime_overrides["parser.pre_delay_max_seconds"] = st.number_input(
                "解析前最大等待秒数（parser.pre_delay_max_seconds）",
                min_value=0.0,
                value=float(base_config.parser.pre_delay_max_seconds),
                step=0.1,
            )
            runtime_overrides["task.completion_delay_min_seconds"] = st.number_input(
                "任务完成后最小等待秒数（task.completion_delay_min_seconds）",
                min_value=0.0,
                value=float(base_config.task.completion_delay_min_seconds),
                step=0.1,
            )
            runtime_overrides["task.completion_delay_max_seconds"] = st.number_input(
                "任务完成后最大等待秒数（task.completion_delay_max_seconds）",
                min_value=0.0,
                value=float(base_config.task.completion_delay_max_seconds),
                step=0.1,
            )
        with col3:
            parser_backoff_text = st.text_input(
                "Parser 重试退避序列（retry.parser_backoff_seconds）",
                value=",".join(str(x) for x in base_config.retry.parser_backoff_seconds),
            )
            gemini_backoff_text = st.text_input(
                "模型重试退避序列（retry.gemini_backoff_seconds）",
                value=",".join(str(x) for x in base_config.retry.gemini_backoff_seconds),
            )
            runtime_overrides["circuit_breaker.parser.consecutive_failures"] = st.number_input(
                "Parser 连续失败熔断阈值（circuit_breaker.parser.consecutive_failures）",
                min_value=1,
                value=base_config.circuit_breaker.parser.consecutive_failures,
                step=1,
            )
            runtime_overrides["circuit_breaker.gemini.consecutive_failures"] = st.number_input(
                "模型连续失败熔断阈值（circuit_breaker.gemini.consecutive_failures）",
                min_value=1,
                value=base_config.circuit_breaker.gemini.consecutive_failures,
                step=1,
            )
            if base_config.provider == "volcengine":
                runtime_overrides["volcengine.stream_usage"] = st.checkbox(
                    "开启流式用量统计（volcengine.stream_usage）",
                    value=bool(base_config.volcengine.stream_usage),
                )
                runtime_overrides["volcengine.use_batch_chat"] = st.checkbox(
                    "开启批量 Chat（volcengine.use_batch_chat）",
                    value=bool(base_config.volcengine.use_batch_chat),
                )
                runtime_overrides["volcengine.batch_size"] = st.number_input(
                    "批量 Chat 批次大小（volcengine.batch_size）",
                    min_value=1,
                    max_value=50,
                    value=int(base_config.volcengine.batch_size),
                    step=1,
                )

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

    table_placeholder = st.empty()
    status_placeholder = st.empty()

    if st.button("开始执行", type="primary"):
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
            runtime_overrides["retry.parser_backoff_seconds"] = _parse_backoff(parser_backoff_text)
            runtime_overrides["retry.gemini_backoff_seconds"] = _parse_backoff(gemini_backoff_text)
            if base_config.provider == "volcengine":
                token_text = (volc_max_tokens_text or "").strip()
                runtime_overrides["volcengine.max_completion_tokens"] = int(token_text) if token_text else None
            config_manager.override_mapping(runtime_overrides)
            runtime_config = config_manager.get_config()
        except Exception as exc:  # noqa: BLE001
            st.error(f"运行时配置无效: {exc}")
            st.stop()

        _render_table(table_placeholder, tasks, show_category=app_mode == AppMode.CATEGORY_ANALYSIS)
        status_placeholder.info("任务执行中...")

        asyncio.run(
            _run_scheduler(
                config=runtime_config,
                api_key=api_key,
                default_user_prompt=default_user_prompt or "",
                output_format=output_format,
                tasks=tasks,
                show_category=app_mode == AppMode.CATEGORY_ANALYSIS,
                cache=cache,
                table_placeholder=table_placeholder,
                status_placeholder=status_placeholder,
            )
        )

        st.session_state["last_tasks"] = tasks
        st.session_state["last_app_mode"] = app_mode.value
        st.session_state["last_default_user_prompt"] = default_user_prompt
        st.session_state["last_output_format"] = output_format
        status_placeholder.success("任务执行完成")

    if st.session_state.get("last_tasks"):
        restore_tasks = st.session_state["last_tasks"]
        last_mode_value = str(st.session_state.get("last_app_mode", AppMode.VIDEO_PROMPT.value))
        try:
            last_mode = AppMode(last_mode_value)
        except ValueError:
            last_mode = AppMode.VIDEO_PROMPT

        is_category_mode = last_mode == AppMode.CATEGORY_ANALYSIS

        st.subheader("导出结果")
        if is_category_mode:
            excel_col, markdown_col, tip_col = st.columns([1, 1, 3])
        else:
            excel_col, tip_col = st.columns([1, 3])
            markdown_col = None

        with tip_col:
            st.info("请尽快导出结果查看完整提示词，避免刷新后结果丢失，导出的 Excel 可直接导入 Lumen")

        with excel_col:
            export_excel_clicked = st.button("导出 Excel")

        export_markdown_clicked = False
        if is_category_mode and markdown_col is not None:
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
                include_category=is_category_mode,
            )
            st.success(f"导出成功: {output_file}")
            with output_file.open("rb") as f:
                st.download_button(
                    label="下载 Excel",
                    data=f.read(),
                    file_name=output_file.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        if export_markdown_clicked:
            markdown_exporter = MarkdownExporter(output_root="exports")
            try:
                result = markdown_exporter.export_by_category(tasks=restore_tasks)
            except ValueError as exc:
                st.warning(str(exc))
            else:
                st.success(
                    f"Markdown 导出成功：{result.exported_category_count} 个类目，"
                    f"{result.exported_task_count} 条视频脚本"
                )
                with result.zip_path.open("rb") as f:
                    st.download_button(
                        label="下载 Markdown ZIP",
                        data=f.read(),
                        file_name=result.zip_path.name,
                        mime="application/zip",
                    )


if __name__ == "__main__":
    main()
