# -*- coding: utf-8 -*-
"""TaskRunner 测试（tasks.md 4.2/14.1）：状态机、指数退避重试≤2、重启恢复（Redis锁去重）。"""
import asyncio
import uuid

import pytest

from app.infrastructure import redis_client, task_runner
from app.models import AsyncTask


@pytest.fixture
async def runner_env(monkeypatch, session_factory, fake_redis):
    """注入测试会话工厂 + 隔离handler注册表 + 屏蔽真实 sleep + 绑定事件循环。"""
    monkeypatch.setattr(task_runner, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(task_runner, "_handlers", {})
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(task_runner, "_loop", loop)
    sleeps: list[float] = []

    async def fast_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(task_runner.asyncio, "sleep", fast_sleep)
    return sleeps


def _make_task(user_id: str, task_type: str = "structure") -> AsyncTask:
    """构造测试任务；type 取真实枚举值（t_async_task.type 为枚举列）。"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return AsyncTask(user_id=user_id, type=task_type, ref_id="ref", status="pending", created_at=now)


async def test_state_flow_done(session_factory, runner_env):
    from app.db import get_db  # noqa: F401  确保db模块加载

    async def ok_handler(db, task):
        return {"ok": True}

    task_runner.register_handler("structure", ok_handler)
    async with session_factory() as db:
        task = _make_task("u-1", "structure")
        db.add(task)
        await db.commit()
        task_id = task.id

    await task_runner._execute_task(task_id)

    async with session_factory() as db:
        fresh = await db.get(AsyncTask, task_id)
        assert fresh.status == "done"
        assert fresh.error_msg is None


async def test_retry_then_failed(session_factory, runner_env):
    """失败指数退避重试≤2次（1s→2s），仍失败标记 failed。"""
    calls = {"n": 0}

    async def bad_handler(db, task):
        calls["n"] += 1
        raise RuntimeError("boom")

    task_runner.register_handler("structure", bad_handler)
    async with session_factory() as db:
        task = _make_task("u-1", "structure")
        db.add(task)
        await db.commit()
        task_id = task.id

    await task_runner._execute_task(task_id)

    async with session_factory() as db:
        fresh = await db.get(AsyncTask, task_id)
        assert fresh.status == "failed"
        assert "boom" in fresh.error_msg
        assert fresh.retry_count == 2
        assert calls["n"] == 3  # 首次 + 2次重试


async def test_retry_backoff_delays(session_factory, runner_env):
    async def bad_handler(db, task):
        raise RuntimeError("x")

    task_runner.register_handler("structure", bad_handler)
    async with session_factory() as db:
        task = _make_task("u-1", "structure")
        db.add(task)
        await db.commit()
        task_id = task.id

    await task_runner._execute_task(task_id)
    assert runner_env == [1.0, 2.0]  # 指数退避 1s→2s


async def test_unregistered_type_fails_immediately(session_factory, runner_env):
    # "ocr" 是合法枚举值但注册表已被fixture清空 → 无处理器
    async with session_factory() as db:
        task = _make_task("u-1", "ocr")
        db.add(task)
        await db.commit()
        task_id = task.id

    await task_runner._execute_task(task_id)
    async with session_factory() as db:
        fresh = await db.get(AsyncTask, task_id)
        assert fresh.status == "failed"
        assert "无已注册处理器" in fresh.error_msg


async def test_done_task_not_rerun(session_factory, runner_env):
    executed = {"n": 0}

    async def once_handler(db, task):
        executed["n"] += 1
        return {}

    task_runner.register_handler("structure", once_handler)
    async with session_factory() as db:
        task = _make_task("u-1", "structure")
        task.status = "done"
        db.add(task)
        await db.commit()
        task_id = task.id

    await task_runner._execute_task(task_id)
    assert executed["n"] == 0


async def test_startup_recovery_with_lock(session_factory, runner_env, fake_redis, monkeypatch):
    """重启恢复：pending/running 重新提交；Redis锁下仅一个worker执行。"""
    submitted: list[str] = []
    monkeypatch.setattr(task_runner, "_submit", lambda task_id: submitted.append(task_id))

    async with session_factory() as db:
        for status in ("pending", "running", "done"):
            t = _make_task("u-1")
            t.type = "structure"
            t.status = status
            db.add(t)
        await db.commit()

    await task_runner._recover_pending_tasks()
    assert len(submitted) == 2  # done 不恢复

    # 第二个worker：锁已被持有 → 不再重复提交
    submitted.clear()
    fake = fake_redis  # 锁已在恢复时写入（EX 30）
    assert await fake.get("taskrunner:recover:lock")
    await task_runner._recover_pending_tasks()
    assert submitted == []


async def test_startup_recovery_without_redis(session_factory, runner_env, monkeypatch):
    """Redis不可用时退化为单实例直接恢复（不抛异常）。"""
    submitted: list[str] = []
    monkeypatch.setattr(task_runner, "_submit", lambda task_id: submitted.append(task_id))

    def broken_redis():
        raise ConnectionError("redis down")

    monkeypatch.setattr(redis_client, "get_redis", broken_redis)

    async with session_factory() as db:
        t = _make_task("u-1")
        t.type = "structure"
        db.add(t)
        await db.commit()

    await task_runner._recover_pending_tasks()
    assert len(submitted) == 1
