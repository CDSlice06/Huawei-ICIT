# -*- coding: utf-8 -*-
"""双账号数据隔离测试（tasks.md 3.3/14.1）：用户B无法访问用户A的任何资源（统一404）。"""
import uuid

from tests.conftest import FakeRedis  # noqa: F401  (确保 conftest 已加载)


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": "Passw0rd123"}
    )
    assert resp.status_code == 200
    return resp.json()["data"]["token"]


async def _make_owned_resources(client, token: str) -> dict:
    """为用户A构造素材/任务/卡片/知识库资源。"""
    headers = {"Authorization": f"Bearer {token}"}
    kb = await client.post("/api/knowledge-bases", json={"name": "A的库"}, headers=headers)
    assert kb.status_code == 200, kb.text
    kb_id = kb.json()["data"]["id"]

    imp = await client.post(
        "/api/assets/text", json={"content": "A的私有笔记内容", "kb_id": kb_id}, headers=headers
    )
    assert imp.status_code == 202, imp.text
    return {
        "kb_id": kb_id,
        "task_id": imp.json()["data"]["task_id"],
        "asset_id": imp.json()["data"]["asset_id"],
    }


async def test_cross_user_access_returns_404(client, no_submit):
    email_a, email_b = f"a-{uuid.uuid4().hex[:6]}@t.cn", f"b-{uuid.uuid4().hex[:6]}@t.cn"
    token_a = await _register(client, email_a)
    token_b = await _register(client, email_b)
    res = await _make_owned_resources(client, token_a)

    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 任务状态：他人任务404
    assert (await client.get(f"/api/tasks/{res['task_id']}", headers=headers_b)).status_code == 404
    # 素材：他人404
    assert (await client.get(f"/api/assets/{res['asset_id']}", headers=headers_b)).status_code == 404
    # 知识库导图：他人kb_id 404
    assert (await client.get(f"/api/mind-maps/{res['kb_id']}", headers=headers_b)).status_code == 404
    # 删除他人知识库 404
    assert (
        await client.delete(f"/api/knowledge-bases/{res['kb_id']}?confirm=true", headers=headers_b)
    ).status_code == 404
    # 移动卡片到他人库：目标库不存在 404（归属校验）
    move = await client.post(
        "/api/cards/nonexistent/move", json={"target_kb_id": res["kb_id"]}, headers=headers_b
    )
    assert move.status_code == 404


async def test_review_and_card_isolation(client, no_submit, session_factory):
    email_a = f"c-{uuid.uuid4().hex[:6]}@t.cn"
    token_a = await _register(client, email_a)
    token_b = await _register(client, f"d-{uuid.uuid4().hex[:6]}@t.cn")
    res = await _make_owned_resources(client, token_a)

    # A 走完结构化（mock MaaS）拿到卡片
    from sqlalchemy import select

    from app.models import AsyncTask
    from app.services import card_service

    class FakeMaaS:
        async def chat_json(self, messages, **kwargs):
            return {
                "title": "隔离测试卡片",
                "summary": "摘要",
                "key_points": ["p1", "p2", "p3"],
                "qa_pairs": [{"question": "q", "answer": "a"}],
                "tags": ["t"],
            }

    import app.services.card_service as cs

    original = cs.get_maas_client
    cs.get_maas_client = lambda: FakeMaaS()
    try:
        async with session_factory() as db:
            task = (
                await db.execute(select(AsyncTask).where(AsyncTask.id == res["task_id"]))
            ).scalar_one()
            await card_service.structure_task_handler(db, task)
    finally:
        cs.get_maas_client = original

    from app.models import KnowledgeCard

    async with session_factory() as db:
        card = (
            await db.execute(
                select(KnowledgeCard).where(KnowledgeCard.asset_id == res["asset_id"])
            )
        ).scalar_one()

    headers_b = {"Authorization": f"Bearer {token_b}"}
    # B 查看/编辑/删除 A 的卡片 → 404
    assert (await client.get(f"/api/cards/{card.id}", headers=headers_b)).status_code == 404
    assert (
        await client.put(f"/api/cards/{card.id}", json={"title": "hacked"}, headers=headers_b)
    ).status_code == 404
    assert (await client.delete(f"/api/cards/{card.id}", headers=headers_b)).status_code == 404
    # A 自己正常访问
    headers_a = {"Authorization": f"Bearer {token_a}"}
    assert (await client.get(f"/api/cards/{card.id}", headers=headers_a)).status_code == 200
