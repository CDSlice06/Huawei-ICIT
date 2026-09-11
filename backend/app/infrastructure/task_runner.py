"""异步任务执行器（tasks.md 4.2，design.md §2.1.3.1、§2.7.3）。

- ThreadPoolExecutor(max_workers=8)，任务表持久化，SSE/轮询双通道状态推送
- 状态机 pending→running→done/failed，失败指数退避重试≤2次（1s→2s）
- 服务重启恢复：启动时扫描 pending/running 任务重新提交（spec §4.2.1）
- 单用户并发闸门：进行中任务数≤2（API层校验，design.md §2.1.3.1）
"""
import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.db import AsyncSessionLocal
from app.logging_config import log_action
from app.models import AsyncTask

logger = logging.getLogger(__name__)

# 任务状态事件（进程内通知，SSE端点订阅）
_task_events: dict[str, list[asyncio.Event]] = {}
_events_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None

# handler 注册表：type → 协程(db: AsyncSession, task: AsyncTask) -> dict(result)
_handlers: dict[str, Callable[[Any, AsyncTask], Awaitable[dict]]] = {}

_executor: ThreadPoolExecutor | None = None


def register_handler(task_type: str, handler: Callable[[Any, AsyncTask], Awaitable[dict]]) -> None:
    """注册任务类型处理器（structure/map_gen/ocr/mistake_parse）。"""
    _handlers[task_type] = handler


def init_runner(loop: asyncio.AbstractEventLoop) -> None:
    """FastAPI lifespan 中调用：初始化线程池并恢复未完成任务。"""
    global _executor, _loop
    _loop = loop
    _executor = ThreadPoolExecutor(max_workers=settings.TASK_MAX_WORKERS, thread_name_prefix="mw-task")
    # 重启恢复：扫描 pending/running 任务重新提交
    asyncio.ensure_future(_recover_pending_tasks())


async def shutdown_runner() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None


def subscribe(task_id: str) -> asyncio.Event:
    """SSE端点订阅任务状态变更事件。"""
    event = asyncio.Event()
    with _events_lock:
        _task_events.setdefault(task_id, []).append(event)
    return event


def unsubscribe(task_id: str, event: asyncio.Event) -> None:
    with _events_lock:
        listeners = _task_events.get(task_id, [])
        if event in listeners:
            listeners.remove(event)
        if not listeners:
            _task_events.pop(task_id, None)


def _notify(task_id: str) -> None:
    """通知所有订阅者（线程池线程 → 事件循环线程安全调用）。"""
    with _events_lock:
        events = list(_task_events.get(task_id, []))
    if events and _loop is not None:
        for ev in events:
            _loop.call_soon_threadsafe(ev.set)


async def _recover_pending_tasks() -> None:
    """服务重启恢复（spec §4.2.1）：pending/running 任务重新提交。

    多 worker 部署下以 Redis SETNX 锁保证仅一个 worker 执行恢复，
    避免同一任务被多个 worker 重复提交/执行；Redis 不可用时退化为各 worker 均尝试恢复
    （单实例默认场景，_execute_task 的终态检查可挡住已完成任务）。
    """
    import socket

    from app.infrastructure import redis_client

    lock_key = "taskrunner:recover:lock"
    lock_acquired = False
    try:
        lock_acquired = bool(
            await redis_client.get_redis().set(
                lock_key, socket.gethostname(), nx=True, ex=30
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("恢复锁获取失败（Redis不可用），按单实例执行恢复: %s", exc)
        lock_acquired = True
    if not lock_acquired:
        logger.info("重启恢复由其他worker执行，本worker跳过")
        return
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(AsyncTask).where(AsyncTask.status.in_(["pending", "running"]))
            )
            tasks = result.scalars().all()
            for task in tasks:
                task.status = "pending"
            await db.commit()
            for task in tasks:
                _submit(str(task.id))
            if tasks:
                logger.info("重启恢复：%d 个未完成任务重新提交", len(tasks))
    except Exception as exc:  # noqa: BLE001
        logger.error("重启恢复扫描失败: %s", exc)


def _submit(task_id: str) -> None:
    """将任务提交到线程池（独立DB会话，避免与请求会话竞争）。"""
    if _executor is None:
        logger.error("TaskRunner未初始化，任务%s提交失败", task_id)
        return
    _executor.submit(_execute_task_blocking, task_id)


def submit_task(task_id: str) -> None:
    """API层创建任务记录后调用。"""
    _submit(task_id)


def _execute_task_blocking(task_id: str) -> None:
    """线程池内执行：独立事件循环运行异步handler。"""
    asyncio.run(_execute_task(task_id))


async def _execute_task(task_id: str) -> None:
    started = time.monotonic()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(AsyncTask).where(AsyncTask.id == task_id))
        task = result.scalar_one_or_none()
        if task is None or task.status in ("done",):
            return

        handler = _handlers.get(task.type)
        if handler is None:
            task.status = "failed"
            task.error_msg = f"任务类型 {task.type} 无已注册处理器"
            await db.commit()
            _notify(task_id)
            return

        task.status = "running"
        await db.commit()
        _notify(task_id)

        retries = 0
        backoff = 1.0
        while True:
            try:
                output = await handler(db, task)
                task.status = "done"
                task.error_msg = None
                await db.commit()
                log_action(
                    logger, f"task:{task.type}", user_id=task.user_id,
                    duration_ms=round((time.monotonic() - started) * 1000, 1),
                    status="done", task_id=task_id,
                )
                break
            except Exception as exc:  # noqa: BLE001
                if retries < settings.TASK_RETRY_MAX:
                    retries += 1
                    task.retry_count = retries
                    await db.commit()
                    logger.warning(
                        "任务%s第%d次失败，%ss后重试: %s", task_id, retries, backoff, exc
                    )
                    await asyncio.sleep(backoff)
                    backoff *= 2
                    continue
                task.status = "failed"
                task.error_msg = str(exc)[:2000]
                await db.commit()
                log_action(
                    logger, f"task:{task.type}", user_id=task.user_id,
                    duration_ms=round((time.monotonic() - started) * 1000, 1),
                    status="failed", error=str(exc)[:200],
                )
                break
        _notify(task_id)


async def wait_task_done(task_id: str, timeout: float = 180.0) -> bool:
    """等待任务完成事件（SSE生成器内部使用）。"""
    event = subscribe(task_id)
    try:
        return await asyncio.wait_for(event.wait(), timeout=timeout)
    finally:
        unsubscribe(task_id, event)