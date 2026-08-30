"""令牌桶限速器：campaign 级每分钟配额 + 全局最小间隔，可注入时钟便于测试。"""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """按速率补充令牌的桶。capacity 决定突发上限（默认 = 每分钟配额）。"""

    def __init__(self, rate_per_minute: float, capacity: float | None = None, clock=time.monotonic):
        self.rate = max(0.1, float(rate_per_minute)) / 60.0  # 每秒补充
        self.capacity = float(capacity if capacity and capacity > 0 else max(1, rate_per_minute))
        self.tokens = self.capacity
        self.clock = clock
        self._last = self.clock()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self._last) * self.rate)
        self._last = now

    def acquire(self, timeout: float = 30.0) -> bool:
        """取一个令牌；超时返回 False（不阻塞调度线程太久）。"""
        deadline = self.clock() + timeout
        while True:
            with self._lock:
                self._refill()
                if self.tokens >= 1:
                    self.tokens -= 1
                    return True
                wait = (1 - self.tokens) / self.rate
            if self.clock() + wait > deadline:
                return False
            time.sleep(min(wait, 0.5))


class GlobalPacer:
    """全局最小发送间隔（防止多活动叠加突发）。"""

    def __init__(self, min_interval: float = 1.0, clock=time.monotonic):
        self.min_interval = max(0.0, min_interval)
        self.clock = clock
        self._next_at = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self.clock()
                if now >= self._next_at:
                    self._next_at = now + self.min_interval
                    return
                wait = self._next_at - now
            time.sleep(min(wait, 0.5))
