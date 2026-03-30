"""运行面板刷新节流。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RuntimeRefreshGate:
    min_interval_seconds: float
    stopping_interval_seconds: float = 0.25
    _last_refresh_at: float | None = None

    def should_refresh(self, *, now: float, stopping: bool = False) -> bool:
        interval = (
            self.stopping_interval_seconds if stopping else self.min_interval_seconds
        )
        if self._last_refresh_at is None or now - self._last_refresh_at >= interval:
            self._last_refresh_at = now
            return True
        return False
