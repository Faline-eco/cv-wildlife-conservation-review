from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    """Simple token bucket limiter allowing up to max_calls per 1-second window."""

    def __init__(self, max_calls_per_sec: int = 6) -> None:
        self.max_calls = max_calls_per_sec
        self.window = 1.0
        self.calls = deque()

    def wait(self) -> None:
        now = time.time()
        self._prune(now)
        if len(self.calls) >= self.max_calls:
            # sleep until the oldest call leaves the window
            earliest = self.calls[0]
            sleep_for = (earliest + self.window) - now
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.time()
            self._prune(now)
        self.calls.append(time.time())

    def _prune(self, now: float) -> None:
        while self.calls and (now - self.calls[0]) > self.window:
            self.calls.popleft()
