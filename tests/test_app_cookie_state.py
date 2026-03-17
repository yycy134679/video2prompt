from __future__ import annotations

from app import SESSION_COOKIE_INPUT_RESET, _consume_cookie_input_reset, _resolve_cookie_failure_state
from video2prompt.models import Task


def test_cookie_failure_state_clears_after_successful_tasks() -> None:
    tasks = [Task(pid="1", original_link="a", error_message="")]

    result = _resolve_cookie_failure_state(previous_failed=True, notice="", tasks=tasks)

    assert not result


def test_cookie_failure_state_keeps_previous_value_when_no_tasks() -> None:
    result = _resolve_cookie_failure_state(previous_failed=True, notice="", tasks=[])

    assert result


def test_cookie_failure_state_resets_after_cookie_saved() -> None:
    tasks = [Task(pid="1", original_link="a", error_message="Cookie 可能失效或需要过验证码，请重新复制浏览器 Cookie")]

    result = _resolve_cookie_failure_state(previous_failed=True, notice="saved", tasks=tasks)

    assert not result


def test_cookie_input_reset_clears_value_before_next_render() -> None:
    session_state = {
        "douyin_cookie_input": "sessionid=abc",
        SESSION_COOKIE_INPUT_RESET: True,
    }

    _consume_cookie_input_reset(session_state)

    assert session_state["douyin_cookie_input"] == ""
    assert SESSION_COOKIE_INPUT_RESET not in session_state
