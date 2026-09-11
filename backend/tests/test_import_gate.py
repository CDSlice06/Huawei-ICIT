# -*- coding: utf-8 -*-
"""文本导入与并发闸门测试（tasks.md 4.1/14.1）：≤5000字符、闸门≤2→429、素材先于任务落盘、202。"""
import uuid

from sqlalchemy import select

from app.models import AsyncTask, KnowledgeAsset


def _email() -> str:
    return f"gate-{uuid.uuid4().hex[:8]}@test.cn"


async def test_import_text_returns_202_and_persists(client, auth_headers, no_submit, session_factory):
    resp = await client.post(
        "/api/assets/text",
        json={"content": "导图测试内容：遗忘曲线的核心要点。"},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    data = resp.json()["data"]
    assert data["task_id"] and data["asset_id"]

    async with session_factory() as db:
        asset = (
            await db.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == data["asset_id"]))
        ).scalar_one()
        task = (
            await db.execute(select(AsyncTask).where(AsyncTask.id == data["task_id"]))
        ).scalar_one()
        assert asset.parse_status == "parsing"
        assert asset.raw_content.startswith("导图测试内容")
        assert task.type == "structure" and task.status == "pending"
        assert task.user_id == asset.user_id  # user_id 隔离冗余


async def test_import_over_5000_chars_422(client, auth_headers):
    resp = await client.post(
        "/api/assets/text", json={"content": "长" * 5001}, headers=auth_headers
    )
    assert resp.status_code == 422
    assert "5000" in resp.json()["message"]


async def test_concurrency_gate_429(client, auth_headers, no_submit):
    """进行中任务数达2后，第3次导入返回429（design §2.1.3.1）。"""
    for i in range(2):
        ok = await client.post(
            "/api/assets/text", json={"content": f"第{i}篇笔记"}, headers=auth_headers
        )
        assert ok.status_code == 202
    blocked = await client.post(
        "/api/assets/text", json={"content": "第三篇被拒绝"}, headers=auth_headers
    )
    assert blocked.status_code == 429
    assert "稍候" in blocked.json()["message"]


async def test_gate_counts_running_too(client, auth_headers, no_submit, session_factory):
    """pending + running 合并计数：1 pending + 1 running 也应触发闸门。"""
    me = await client.get("/api/auth/me")
    user_id = me.json()["data"]["id"]

    for i in range(2):
        await client.post(
            "/api/assets/text", json={"content": f"计数{i}"}, headers=auth_headers
        )
    # 将其中一个任务置为 running，仍是"进行中"
    async with session_factory() as db:
        task = (
            await db.execute(
                select(AsyncTask).where(
                    AsyncTask.user_id == user_id, AsyncTask.status == "pending"
                )
            )
        ).scalars().first()
        task.status = "running"
        await db.commit()

    blocked = await client.post(
        "/api/assets/text", json={"content": "仍被拒绝"}, headers=auth_headers
    )
    assert blocked.status_code == 429


async def test_import_default_kb_auto_created(client, auth_headers, no_submit, session_factory):
    """kb_id 缺省：自动创建/使用默认知识库（spec §5.2.1规则6 一键零配置）。"""
    resp = await client.post(
        "/api/assets/text", json={"content": "无库导入"}, headers=auth_headers
    )
    assert resp.status_code == 202
    async with session_factory() as db:
        asset = (
            await db.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == resp.json()["data"]["asset_id"]))
        ).scalar_one()
        assert asset.kb_id is not None


async def test_import_invalid_kb_422(client, auth_headers):
    resp = await client.post(
        "/api/assets/text",
        json={"content": "内容", "kb_id": "not-exist-kb"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
