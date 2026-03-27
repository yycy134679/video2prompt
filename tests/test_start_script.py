from __future__ import annotations

from pathlib import Path


SCRIPT_PATH = Path("scripts/start.sh")


def test_start_script_defaults_to_port_8512() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'DEFAULT_STREAMLIT_PORT="8512"' in text


def test_start_script_prefers_video2prompt_port_env_over_port_env() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'STREAMLIT_PORT="${VIDEO2PROMPT_STREAMLIT_PORT:-${PORT:-$DEFAULT_STREAMLIT_PORT}}"' in text


def test_start_script_passes_streamlit_port_explicitly() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert '--server.port "$STREAMLIT_PORT"' in text
