# -*- coding: utf-8 -*-
"""pytest 共享 fixtures（tasks.md 14.1）。

按 tasks.md 14.1 约定：纯业务逻辑测试跑 aiosqlite 兼容层提速；
涉及 FULLTEXT ngram 检索效果的表结构验证须在 MySQL 测试容器执行
（SQLite 无 ngram parser），此处通过注册同名 JSON_UNQUOTE 函数
使 STORED GENERATED 生成列在 SQLite 下可用（仅支撑业务读写）。

基础设施：
- DATABASE_URL 重定向到临时 SQLite 文件（引擎惰性连接，业务测试经
  monkeypatch app.db.AsyncSessionLocal 注入测试会话工厂）
- FakeRedis 内存假实现（会话/缓存/SETNX 语义），经 monkeypatch 注入
- httpx.AsyncClient + ASGITransport 直连 FastAPI 应用（不跑 lifespan，
  避免真实调度器/重启恢复干扰）
"""
import os
import tempfile
import time

# 必须先于任何 app.* 导入设置环境变量（config.py 在导入时读取）
_TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "memweave_pytest.db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"
os.environ["ENABLE_SCHEDULER"] = "false"


class FakeRedis:
    """最小异步 Redis 假实现：get/set(ex,nx)/delete/eval 覆盖会话与缓存语义。"""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}
        self.clock = time.monotonic

    async def get(self, key: str) -> str | None:
        item = self._store.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires < self.clock():
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and key in self._store:
            v, exp = self._store[key]
            if exp is None or exp >= self.clock():
                return False
        expires = self.clock() + ex if ex else None
        self._store[key] = (value, expires)
        return True

    async def delete(self, *keys: str) -> int:
        removed = 0
        for k in keys:
            if k in self._store:
                self._store.pop(k, None)
                removed += 1
        return removed

    async def expire(self, key: str, seconds: int) -> bool:
        item = self._store.get(key)
        if item is None:
            return False
        self._store[key] = (item[0], self.clock() + seconds)
        return True

    async def eval(self, script: str, numkeys: int, *args):  # 调度锁 Lua 续期/释放
        key = args[0]
        if "EXPIRE" in script:  # 续期：值匹配才续
            item = self._store.get(key)
            if item and item[0] == args[1]:
                self._store[key] = (item[0], self.clock() + int(args[2]))
                return 1
            return 0
        # 释放：值匹配才删
        item = self._store.get(key)
        if item and item[0] == args[1]:
            self._store.pop(key, None)
            return 1
        return 0

    async def aclose(self) -> None:
        pass


import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)

from app.infrastructure import redis_client  # noqa: E402
from app.models import Base  # noqa: E402


@pytest_asyncio.fixture
async def db_engine():
    """每测试独立建表（drop_all + create_all），SQLite 文件库。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{_TEST_DB_PATH}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis", lambda: fake)
    return fake


@pytest_asyncio.fixture
async def client(monkeypatch, session_factory, fake_redis):
    """API 测试客户端：注入测试会话工厂 + FakeRedis。"""
    from app import db as app_db
    from app.main import app

    monkeypatch.setattr(app_db, "AsyncSessionLocal", session_factory)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client):
    """注册一个测试用户并返回 Bearer 请求头。"""
    import uuid

    resp = await client.post(
        "/api/auth/register",
        json={"email": f"user-{uuid.uuid4().hex[:8]}@test.cn", "password": "Passw0rd123"},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def no_submit(monkeypatch):
    """屏蔽任务提交（闸门测试需任务保持 pending）。"""
    from app.infrastructure import task_runner

    submitted: list[str] = []
    monkeypatch.setattr(task_runner, "submit_task", lambda task_id: submitted.append(task_id))
    return submitted


@pytest_asyncio.fixture
async def kb_with_user(client, auth_headers):
    """已注册用户上下文（user_id 与 auth_headers 指向同一账号，供直接构造业务数据）。"""
    me = await client.get("/api/auth/me", headers=auth_headers)
    return {"user_id": me.json()["data"]["id"], "headers": auth_headers}
