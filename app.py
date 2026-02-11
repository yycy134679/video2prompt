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
from video2prompt.models import Task, TaskInput
from video2prompt.parser_client import ParserClient
from video2prompt.task_scheduler import TaskScheduler
from video2prompt.validator import InputValidator
from video2prompt.volcengine_client import VolcengineClient


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
        "FPS": task.fps_used,
        "错误": task.error_message,
        "模型输出预览": task.gemini_output[:120],
        "缓存命中": task.cache_hit,
    }


def _rows(tasks: list[Task]) -> list[dict[str, Any]]:
    return [_task_to_row(task) for task in tasks]


def _render_table(table_placeholder, tasks: list[Task]) -> None:
    table_placeholder.dataframe(
        _rows(tasks),
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
    tasks: list[Task],
    cache: CacheStore,
    table_placeholder,
    status_placeholder,
    skip_batch_rest_once: bool,
):
    parser_http = httpx.AsyncClient(timeout=config.parser.timeout_seconds)
    model_timeout = config.gemini.timeout_seconds if config.provider == "gemini" else config.volcengine.timeout_seconds
    model_http = httpx.AsyncClient(timeout=model_timeout)

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
    )

    cancel_event = asyncio.Event()
    skip_event = asyncio.Event()
    if skip_batch_rest_once:
        skip_event.set()

    def on_update(_: Task) -> None:
        _render_table(table_placeholder, tasks)

    def on_countdown(remain: int) -> None:
        status_placeholder.info(f"批次休息中，剩余 {remain}s（已支持跳过下一段休息）")

    try:
        await scheduler.run(
            tasks=tasks,
            user_prompt=default_user_prompt,
            on_update=on_update,
            on_batch_countdown=on_countdown,
            cancel_event=cancel_event,
            skip_rest_event=skip_event,
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

    logger = setup_logging(base_config.logging.file_path, base_config.logging.level)
    st.session_state["logger"] = logger

    cache = CacheStore(base_config.cache.db_path)
    asyncio.run(cache.init_db())

    if "default_user_prompt" not in st.session_state:
        saved_prompt = asyncio.run(cache.load_system_prompt())
        st.session_state["default_user_prompt"] = saved_prompt or "请基于视频内容生成高质量 Sora 提示词，中文输出。"

    if base_config.provider == "gemini":
        st.caption(f"当前模型服务商：gemini（model={base_config.gemini.model}）")
    else:
        st.caption(
            "当前模型服务商：volcengine "
            f"（endpoint_id={base_config.volcengine.endpoint_id}，target_model={base_config.volcengine.target_model}）"
        )

    with st.expander("服务状态", expanded=True):
        checker = ParserClient(base_url=base_config.parser.base_url, timeout_seconds=5)
        ok, msg = asyncio.run(checker.health_check())
        if ok:
            st.success(msg)
        else:
            st.warning(msg)

    with st.expander("运行时配置覆盖（仅本次运行生效，不写回 config.yaml）", expanded=False):
        col1, col2, col3 = st.columns(3)
        runtime_overrides: dict[str, Any] = {}
        with col1:
            runtime_overrides["parser.concurrency"] = st.number_input(
                "解析并发数（parser.concurrency）",
                min_value=1,
                max_value=5,
                value=base_config.parser.concurrency,
                step=1,
            )
            runtime_overrides["batch.size"] = st.number_input(
                "每批任务数（batch.size）",
                min_value=50,
                max_value=200,
                value=base_config.batch.size,
                step=10,
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
                st.caption("当前 provider 为 volcengine，未启用 gemini.video_fps 运行时覆盖")
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

        skip_batch_rest_once = st.checkbox("本次运行跳过下一次批次休息", value=False)

    st.subheader("视频解析提示词配置")
    default_user_prompt = st.text_area(
        "DEFAULT_USER_PROMPT",
        value=st.session_state["default_user_prompt"],
        height=180,
    )
    if st.button("保存 DEFAULT_USER_PROMPT"):
        asyncio.run(cache.save_system_prompt(default_user_prompt))
        st.session_state["default_user_prompt"] = default_user_prompt
        st.success("DEFAULT_USER_PROMPT 已保存")

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
        validation = InputValidator.validate_line_count(pid_lines, link_lines)
        if not validation.is_valid:
            st.error(validation.error_message)
            st.stop()

        inputs: list[TaskInput] = InputValidator.parse_lines(pid_text, link_text)
        invalid = [item for item in inputs if not item.is_valid]
        if invalid:
            st.warning(f"检测到 {len(invalid)} 条无效输入，将跳过处理")
            for item in invalid:
                st.write(f"- pid={item.pid or '<空>'} link={item.link or '<空>'} error={item.error}")

        tasks = [Task(pid=item.pid, original_link=item.link) for item in inputs if item.is_valid]
        if not tasks:
            st.error("没有可执行的有效任务")
            st.stop()

        try:
            config_manager.clear_overrides()
            runtime_overrides["retry.parser_backoff_seconds"] = _parse_backoff(parser_backoff_text)
            runtime_overrides["retry.gemini_backoff_seconds"] = _parse_backoff(gemini_backoff_text)
            config_manager.override_mapping(runtime_overrides)
            runtime_config = config_manager.get_config()
        except Exception as exc:  # noqa: BLE001
            st.error(f"运行时配置无效: {exc}")
            st.stop()

        _render_table(table_placeholder, tasks)
        status_placeholder.info("任务执行中...")

        asyncio.run(
            _run_scheduler(
                config=runtime_config,
                api_key=api_key,
                default_user_prompt=default_user_prompt,
                tasks=tasks,
                cache=cache,
                table_placeholder=table_placeholder,
                status_placeholder=status_placeholder,
                skip_batch_rest_once=skip_batch_rest_once,
            )
        )

        st.session_state["last_tasks"] = tasks
        st.session_state["last_default_user_prompt"] = default_user_prompt
        status_placeholder.success("任务执行完成")

    if st.session_state.get("last_tasks"):
        st.subheader("导出结果")
        export_col, tip_col = st.columns([1, 3])
        with tip_col:
            st.info("请尽快导出结果查看完整提示词，避免刷新后结果丢失，导出的 Excel 可直接导入 Lumen")
        with export_col:
            export_clicked = st.button("导出 Excel")

        if export_clicked:
            restore_tasks = st.session_state["last_tasks"]
            exporter = ExcelExporter(template_path="docs/product_prompt_template.xlsx")
            output_dir = Path("exports")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / ExcelExporter.generate_filename()
            exporter.export(tasks=restore_tasks, output_path=str(output_file))
            st.success(f"导出成功: {output_file}")
            with output_file.open("rb") as f:
                st.download_button(
                    label="下载导出文件",
                    data=f.read(),
                    file_name=output_file.name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )


if __name__ == "__main__":
    main()
