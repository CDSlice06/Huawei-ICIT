# -*- coding: utf-8 -*-
"""APScheduler SETNX 锁测试（tasks.md 3.4/14.1）：多 worker 下仅持锁 worker 激活调度。"""
import pytest

from app.infrastructure import scheduler


@pytest.fixture
def sched_env(monkeypatch, fake_redis):
    monkeypatch.setattr(scheduler.settings, "ENABLE_SCHEDULER", True)
    monkeypatch.setattr(scheduler.redis_client, "get_redis", lambda: fake_redis)
    # 每测试重置模块态
    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "_active", False)
    return fake_redis


async def test_first_worker_activates(sched_env, monkeypatch):
    activated = []

    class FakeScheduler:
        def __init__(self, *a, **kw):
            pass

        def add_job(self, *a, **kw):
            pass

        def start(self):
            activated.append(True)

        def shutdown(self, wait=False):
            pass

    monkeypatch.setattr(scheduler, "BackgroundScheduler", FakeScheduler)
    await scheduler.init_scheduler()
    assert activated == [True]
    assert await sched_env.get(scheduler.SCHEDULER_LOCK_KEY)  # 锁已写入


async def test_second_worker_skips(sched_env, monkeypatch):
    """锁被持有时第二实例不激活（锁竞争模拟）。"""
    assert await sched_env.set(scheduler.SCHEDULER_LOCK_KEY, "other-worker", nx=True, ex=60)

    started = {"n": 0}

    class FakeScheduler:
        def __init__(self, *a, **kw):
            started["n"] += 1

        def add_job(self, *a, **kw):
            pass

        def start(self):
            started["n"] += 1

        def shutdown(self, wait=False):
            pass

    monkeypatch.setattr(scheduler, "BackgroundScheduler", FakeScheduler)
    await scheduler.init_scheduler()
    assert started["n"] == 0  # 未激活


async def test_disabled_by_env(sched_env, monkeypatch):
    monkeypatch.setattr(scheduler.settings, "ENABLE_SCHEDULER", False)
    await scheduler.init_scheduler()
    assert await sched_env.get(scheduler.SCHEDULER_LOCK_KEY) is None  # 未抢锁


async def test_renewal_only_when_owned(sched_env):
    """续期 Lua 语义：持锁者可续期，他人不可覆盖。"""
    assert await sched_env.set(scheduler.SCHEDULER_LOCK_KEY, "worker-1", nx=True, ex=60)
    # worker-1 续期成功
    ok = await sched_env.eval(
        scheduler._RENEW_LOCK_LUA, 1, scheduler.SCHEDULER_LOCK_KEY, "worker-1", 60
    )
    assert ok == 1
    # 其他 worker 名义续期被拒
    denied = await sched_env.eval(
        scheduler._RENEW_LOCK_LUA, 1, scheduler.SCHEDULER_LOCK_KEY, "worker-2", 60
    )
    assert denied == 0
