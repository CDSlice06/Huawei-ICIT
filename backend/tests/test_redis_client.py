# -*- coding: utf-8 -*-
"""Redis 客户端封装测试（tasks.md 2.3/14.1）：读写TTL、降级分支（会话抛异常/缓存返None）。"""
import time

import pytest

from app.infrastructure import redis_client
from tests.conftest import FakeRedis


@pytest.fixture
def fake(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis", lambda: fake)
    return fake


async def test_cache_roundtrip_and_ttl(fake):
    now = {"t": time.monotonic()}
    fake.clock = lambda: now["t"]  # type: ignore[method-assign]

    await redis_client.cache_set("k1", "v1", ttl=60)
    assert await redis_client.cache_get("k1") == "v1"

    # 模拟时间流逝超过 TTL
    now["t"] += 120
    assert await redis_client.cache_get("k1") is None


async def test_cache_delete(fake):
    await redis_client.cache_set("k2", "v2", ttl=60)
    await redis_client.cache_delete("k2")
    assert await redis_client.cache_get("k2") is None
    # 空删除不报错
    await redis_client.cache_delete()


async def test_cache_degraded_returns_none(monkeypatch):
    """缓存场景：Redis 异常返回 None（调用方直查 RDS，spec §4.2.2）。"""
    def broken():
        raise ConnectionError("down")

    monkeypatch.setattr(redis_client, "get_redis", broken)
    assert await redis_client.cache_get("k") is None
    await redis_client.cache_set("k", "v", ttl=1)  # 不抛出
    await redis_client.cache_delete("k")  # 不抛出


async def test_session_roundtrip(fake):
    await redis_client.session_set("tok", "user-1", ttl=86400)
    assert await redis_client.session_get("tok") == "user-1"
    await redis_client.session_delete("tok")
    assert await redis_client.session_get("tok") is None


async def test_session_degraded_raises(monkeypatch):
    """会话场景：Redis 异常向上抛出（拒绝登录，安全优先，spec §4.2.2）。"""
    def broken():
        raise ConnectionError("down")

    monkeypatch.setattr(redis_client, "get_redis", broken)
    with pytest.raises(ConnectionError):
        await redis_client.session_get("tok")
    with pytest.raises(ConnectionError):
        await redis_client.session_set("tok", "u", ttl=60)
    with pytest.raises(ConnectionError):
        await redis_client.session_delete("tok")


async def test_cache_key_constants_match_design():
    """五个Key场景常量与 design §2.5.3 对齐。"""
    assert redis_client.KEY_SESSION.format(token="t") == "session:t"
    assert redis_client.KEY_KB_LIST.format(user_id="u") == "kb_list:u"
    assert redis_client.KEY_REVIEW_TODAY.format(user_id="u", date="2026-01-01") == "review_today:u:2026-01-01"
    assert redis_client.KEY_CARD_LIST.format(kb_id="k", page=1) == "card_list:k:1"
