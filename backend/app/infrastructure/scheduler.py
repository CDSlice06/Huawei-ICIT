"""APScheduler 每日调度 + Redis SETNX 单实例锁（tasks.md 3.4，design.md §2.7.4）。

多 worker 下仅持锁 worker 激活调度器（锁 TTL 60s 由续期任务周期续期，
宕机后锁自然过期由存活 worker 抢占）。
注册任务：每日3:00 演示账号重置（handler 9.2填入）、每日1:00 逾期顺延（P1-7填入）。
"""
import asyncio
import logging
import socket

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.infrastructure import redis_client

logger = logging.getLogger(__name__)

SCHEDULER_LOCK_KEY = "scheduler:lock"
LOCK_TTL_SECONDS = 60
RENEW_INTERVAL_SECONDS = 45

# 仅当锁值仍为本 worker 时续期（防止覆盖已抢到锁的其他 worker）
_RENEW_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

# 仅当锁值仍为本 worker 时释放（shutdown时不误删他人锁）
_RELEASE_LOCK_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

_scheduler: BackgroundScheduler | None = None
_active = False
_worker_id = ""


async def init_scheduler() -> None:
    """FastAPI lifespan 启动钩子调用：尝试获取 SETNX 锁并激活调度器。"""
    global _scheduler, _active, _worker_id
    if not settings.ENABLE_SCHEDULER:
        logger.info("调度器未启用（ENABLE_SCHEDULER=false）")
        return

    try:
        _worker_id = socket.gethostname()
        acquired = await redis_client.get_redis().set(
            SCHEDULER_LOCK_KEY, _worker_id, nx=True, ex=LOCK_TTL_SECONDS
        )
        if not acquired:
            logger.info("调度器锁被其他worker持有，本worker跳过调度激活")
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning("调度器锁获取失败（Redis不可用），跳过调度激活: %s", exc)
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _register_jobs(_scheduler)
    _scheduler.start()
    _active = True
    logger.info("调度器已激活（worker=%s）", _worker_id)


async def _renew_lock() -> bool:
    """续期调度锁：仍持锁返回 True；锁已丢失返回 False（应由本实例停止调度）。"""
    result = await redis_client.get_redis().eval(
        _RENEW_LOCK_LUA, 1, SCHEDULER_LOCK_KEY, _worker_id, LOCK_TTL_SECONDS
    )
    return int(result) == 1


def _renew_lock_job() -> None:
    """APScheduler 续期任务（后台线程，无事件循环，用 asyncio.run）。"""
    try:
        renewed = asyncio.run(_renew_lock())
    except Exception as exc:  # noqa: BLE001
        logger.warning("调度器锁续期失败（Redis不可用）: %s", exc)
        return
    if not renewed:
        # 锁被其他 worker 抢占，本实例停止调度避免双实例执行
        logger.warning("调度器锁已被其他worker持有，本worker停止调度")
        asyncio.run(shutdown_scheduler())


def _register_jobs(scheduler: BackgroundScheduler) -> None:
    # 调度锁周期续期（防60s过期后晚启动worker双激活）
    scheduler.add_job(
        _renew_lock_job, "interval", seconds=RENEW_INTERVAL_SECONDS,
        id="scheduler_lock_renew", replace_existing=True,
    )
    # 每日3:00 演示账号重置（handler 在任务9.2填入）
    scheduler.add_job(
        _demo_reset_job, "cron", hour=3, minute=0, id="demo_reset", replace_existing=True
    )
    # 每日1:00 逾期复习顺延（P1-7填入handler，P0仅注册占位）
    scheduler.add_job(
        _postpone_job, "cron", hour=1, minute=0, id="review_postpone", replace_existing=True
    )


def _demo_reset_job() -> None:
    """演示账号每日重置（handler 由任务9.2注入，避免循环导入）。"""
    try:
        from app.services.demo_service import reset_demo_account_sync

        reset_demo_account_sync()
        logger.info("演示账号每日重置完成")
    except ImportError:
        logger.info("演示账号重置handler未就绪（任务9.2未实现），跳过")
    except Exception as exc:  # noqa: BLE001
        logger.error("演示账号每日重置失败: %s", exc)


def _postpone_job() -> None:
    """逾期复习顺延（P1-7实现，P0占位）。"""
    logger.info("逾期顺延任务占位（P1-7未实现），跳过")


async def shutdown_scheduler() -> None:
    global _scheduler, _active
    if _scheduler is not None and _active:
        _scheduler.shutdown(wait=False)
        _active = False
        try:
            await redis_client.get_redis().eval(
                _RELEASE_LOCK_LUA, 1, SCHEDULER_LOCK_KEY, _worker_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("调度器锁释放失败（等待自然过期）: %s", exc)
        logger.info("调度器已停止")