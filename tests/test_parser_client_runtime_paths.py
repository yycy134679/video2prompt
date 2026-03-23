from __future__ import annotations

from pathlib import Path

import pytest

from video2prompt.parser_client import ParserClient


def test_parser_client_default_user_state_store_uses_runtime_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIDEO2PROMPT_APP_SUPPORT_DIR", str(tmp_path / "support"))

    client = ParserClient()

    assert client._user_state_store.path == tmp_path / "support" / "user_state.yaml"
