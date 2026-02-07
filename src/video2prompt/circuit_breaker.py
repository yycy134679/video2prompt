"""熔断器。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class CircuitState:
    consecutive_failures: int = 0
    recent: deque[tuple[datetime, bool]] | None = None


class CircuitBreaker:
    """按连续失败与窗口失败率判断是否熔断。"""

    def __init__(self, consecutive_threshold: int, rate_threshold: float, window_seconds: int = 300):
        self.consecutive_threshold = consecutive_threshold
        self.rate_threshold = rate_threshold
        self.window_seconds = window_seconds
        self._state = CircuitState(recent=deque())

    def record_success(self) -> None:
        self._state.consecutive_failures = 0
        self._state.recent.append((datetime.now(), True))
        self._prune()

    def record_failure(self) -> None:
        self._state.consecutive_failures += 1
        self._state.recent.append((datetime.now(), False))
        self._prune()

    def _prune(self) -> None:
        if self._state.recent is None:
            return
        threshold = datetime.now() - timedelta(seconds=self.window_seconds)
        while self._state.recent and self._state.recent[0][0] < threshold:
            self._state.recent.popleft()

    def is_tripped(self) -> bool:
        if self._state.consecutive_failures >= self.consecutive_threshold:
            return True
        if not self._state.recent:
            return False
        total = len(self._state.recent)
        failures = sum(1 for _, ok in self._state.recent if not ok)
        failure_rate = failures / total if total > 0 else 0
        return failure_rate > self.rate_threshold

    def reset(self) -> None:
        self._state.consecutive_failures = 0
        if self._state.recent is not None:
            self._state.recent.clear()

    @property
    def consecutive_failures(self) -> int:
        return self._state.consecutive_failures
