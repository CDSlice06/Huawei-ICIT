# -*- coding: utf-8 -*-
"""卡片列表性能冒烟测试（tasks.md 6.2/14.1）：1000卡片列表 ≤2秒。

说明：SQLite 本地计时仅作回归护栏；1000卡片≤2秒的正式口径在 MySQL 测试容器复核
（aiosqlite 兼容层不含 ngram/生成列，性能特征不同）。
"""
import time
import uuid
from datetime import datetime, timezone

from app.models import KnowledgeAsset, KnowledgeCard


async def test_list_1000_cards_within_2s(client, auth_headers, session_factory):
    me = await client.get("/api/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["id"]

    kb = await client.post(
        "/api/knowledge-bases", json={"name": "性能测试库"}, headers=auth_headers
    )
    kb_id = kb.json()["data"]["id"]

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with session_factory() as db:
        asset = KnowledgeAsset(
            user_id=user_id, kb_id=kb_id, type="text",
            raw_content="x", parse_status="done", created_at=now,
        )
        db.add(asset)
        await db.flush()
        for i in range(1000):
            db.add(
                KnowledgeCard(
                    user_id=user_id,
                    kb_id=kb_id,
                    asset_id=asset.id,
                    title=f"卡片{i:04d}",
                    summary=f"第{i}张卡片摘要",
                    key_points=["a", "b", "c"],
                    qa_pairs=[{"question": "q", "answer": "a"}],
                    tags=["性能"],
                    review_interval_days=1,
                    review_count=0,
                    created_at=now,
                )
            )
        await db.commit()

    # 回源场景（清空缓存）
    from app.infrastructure import redis_client

    await redis_client.cache_delete(redis_client.KEY_CARD_LIST.format(kb_id=kb_id, page=1))

    start = time.monotonic()
    resp = await client.get(
        f"/api/cards?kb_id={kb_id}&page=1&size=20", headers=auth_headers
    )
    elapsed = time.monotonic() - start
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 1000
    assert elapsed < 2.0, f"1000卡片列表耗时 {elapsed:.2f}s，超出2秒上限"

    # 缓存命中场景
    start = time.monotonic()
    resp2 = await client.get(f"/api/cards?kb_id={kb_id}&page=1&size=20", headers=auth_headers)
    elapsed2 = time.monotonic() - start
    assert resp2.status_code == 200
    assert elapsed2 < 2.0
