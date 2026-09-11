"""异步 Redis 客户端封装（tasks.md 2.3，design.md §2.5.3）。

降级策略（spec §4.2.2）：
- 会话场景：连接异常向上抛出（拒绝登录，安全优先）
- 缓存场景：连接异常返回 None，由调用方直查 RDS
写操作后 delete 失效缓存而非 update（design.md §2.5.3）。
"""
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# 缓存Key场景常量（design.md §2.5.3）
KEY_SESSION = "session:{token}"
KEY_KB_LIST = "kb_list:{user_id}"
KEY_REVIEW_TODAY = "review_today:{user_id}:{date}"
KEY_CARD_LIST = "card_list:{kb_id}:{page}"

_cache_pool: aioredis.ConnectionPool | None = None
_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """懒加载全局 Redis 客户端（连接池 max_connections=50）。"""
    global _cache_pool, _client
    if _client is None:
        _cache_pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL, max_connections=50, decode_responses=True
        )
        _client = aioredis.Redis(connection_pool=_cache_pool)
    return _client


async def close_redis() -> None:
    global _client, _cache_pool
    if _client is not None:
        await _client.aclose()
        _client = None
    if _cache_pool is not None:
        await _cache_pool.disconnect()
        _cache_pool = None


async def cache_get(key: str) -> Any | None:
    """缓存读：Redis 不可用时返回 None（调用方直查 RDS）。"""
    try:
        return await get_redis().get(key)
    except Exception as exc:  # noqa: BLE001 降级：任何Redis异常均视为不可用
        logger.warning("redis cache_get degraded: %s", exc)
        return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    """缓存写：失败仅告警，不影响主流程。"""
    try:
        await get_redis().set(key, value, ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis cache_set degraded: %s", exc)


async def cache_delete(*keys: str) -> None:
    """写操作后失效缓存（delete 而非 update）。失败仅告警。"""
    if not keys:
        return
    try:
        await get_redis().delete(*keys)
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis cache_delete degraded: %s", exc)


CARD_LIST_CACHE_PAGES = 5  # 卡片分页缓存失效覆盖的页数（默认页大小20×5=100卡片内精确失效）


async def invalidate_card_list(kb_id: str, pages: int = CARD_LIST_CACHE_PAGES) -> None:
    """失效某知识库卡片列表分页缓存（写操作后调用）。"""
    await cache_delete(
        *[KEY_CARD_LIST.format(kb_id=kb_id, page=p) for p in range(1, max(pages, 1) + 1)]
    )


async def session_get(token: str) -> str | None:
    """会话读：Redis 不可用时抛出（拒绝登录，安全优先，spec §4.2.2）。"""
    return await get_redis().get(KEY_SESSION.format(token=token))


async def session_set(token: str, user_id: str, ttl: int) -> None:
    """会话写：失败抛出（不允许无会话登录）。"""
    await get_redis().set(KEY_SESSION.format(token=token), user_id, ex=ttl)


async def session_delete(token: str) -> None:
    """会话删除（登出）。失败抛出（登出必须生效）。"""
    await get_redis().delete(KEY_SESSION.format(token=token))