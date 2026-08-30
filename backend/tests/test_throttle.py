"""限速器测试：令牌桶速率与容量、全局间隔。"""

from __future__ import annotations

from app.services.throttle import GlobalPacer, TokenBucket


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_token_bucket_burst_up_to_capacity():
    clock = FakeClock()
    bucket = TokenBucket(60, clock=clock)  # 每分钟 60 → 每秒 1
    # 满桶突发：容量默认 = 60，先连取 60 个
    taken = sum(1 for _ in range(200) if bucket.acquire(timeout=0.01))
    assert taken == 60


def test_token_bucket_refill_rate():
    clock = FakeClock()
    bucket = TokenBucket(60, capacity=2, clock=clock)
    assert bucket.acquire(timeout=0.01)
    assert bucket.acquire(timeout=0.01)
    assert not bucket.acquire(timeout=0.01)  # 空了
    clock.advance(2.0)  # 2 秒 → 补 2 个
    assert bucket.acquire(timeout=0.01)
    assert bucket.acquire(timeout=0.01)
    assert not bucket.acquire(timeout=0.01)


def test_token_bucket_half_refill():
    clock = FakeClock()
    bucket = TokenBucket(120, capacity=1, clock=clock)  # 每秒 2 个
    assert bucket.acquire(timeout=0.01)
    clock.advance(0.5)  # 补 1 个
    assert bucket.acquire(timeout=0.01)
    clock.advance(0.25)  # 补 0.5 个 → 不够
    assert not bucket.acquire(timeout=0.01)


def test_global_pacer_spacing(monkeypatch):
    clock = FakeClock()
    # 让 pacer 内部的 sleep 推进假时钟（模拟真实时间流逝）
    real_sleep = __import__("time").sleep

    def fake_sleep(sec):
        clock.advance(sec)

    import app.services.throttle as throttle_mod
    monkeypatch.setattr(throttle_mod.time, "sleep", fake_sleep)

    pacer = GlobalPacer(min_interval=1.0, clock=clock)
    times = []
    for _ in range(3):
        pacer.acquire()
        times.append(clock.t)
    assert times[0] >= 0
    assert times[1] >= 1.0
    assert times[2] >= 2.0
