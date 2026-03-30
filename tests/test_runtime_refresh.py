from __future__ import annotations

from video2prompt.runtime_refresh import RuntimeRefreshGate


def test_runtime_refresh_gate_blocks_refresh_within_interval() -> None:
    gate = RuntimeRefreshGate(min_interval_seconds=1.0)

    assert gate.should_refresh(now=10.0) is True
    assert gate.should_refresh(now=10.2) is False
    assert gate.should_refresh(now=11.1) is True


def test_runtime_refresh_gate_uses_shorter_interval_for_stopping() -> None:
    gate = RuntimeRefreshGate(min_interval_seconds=1.0, stopping_interval_seconds=0.2)

    assert gate.should_refresh(now=10.0, stopping=True) is True
    assert gate.should_refresh(now=10.1, stopping=True) is False
    assert gate.should_refresh(now=10.25, stopping=True) is True
