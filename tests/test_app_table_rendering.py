from __future__ import annotations

import app

from video2prompt.models import Task, TaskState


class _BrokenTablePlaceholder:
    def __init__(self) -> None:
        self.dataframe_called = False
        self.json_payload = None
        self.warning_messages: list[str] = []

    def dataframe(self, *_args, **_kwargs) -> None:
        self.dataframe_called = True
        raise AttributeError("partially initialized module 'pandas' has no attribute 'core'")

    def json(self, payload, expanded: bool = False) -> None:  # noqa: ANN001
        self.json_payload = (payload, expanded)

    def warning(self, message: str) -> None:
        self.warning_messages.append(message)


def test_render_table_falls_back_to_json_when_dataframe_breaks() -> None:
    placeholder = _BrokenTablePlaceholder()
    tasks = [
        Task(
            pid="1",
            original_link="https://example.com",
            state=TaskState.COMPLETED,
            model_output="ok",
        )
    ]

    app._render_table(placeholder, tasks, show_category=False, show_duration=False)

    assert placeholder.dataframe_called is True
    assert placeholder.warning_messages == ["表格渲染失败，已降级为 JSON 视图"]
    payload, expanded = placeholder.json_payload
    assert expanded is False
    assert payload[0]["pid"] == "1"
