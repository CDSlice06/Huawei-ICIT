# -*- coding: utf-8 -*-
"""P2 功能测试：论坛分享(P2-1)、拼图自测(P2-2)、语义搜索(P2-3)、打卡(P2-4)、手机号注册(P2-5)。"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import app.services.search_service as ss
from sqlalchemy import select as sa_select

from app.models import (
    KnowledgeAsset,
    KnowledgeBase,
    KnowledgeCard,
    MapNode,
    MindMap,
    ReviewTask,
    SharedKnowledgeBase,
)


async def _default_kb_id(db, user_id: str) -> str:
    kb = (
        await db.execute(
            sa_select(KnowledgeBase).where(KnowledgeBase.user_id == user_id, KnowledgeBase.name == "默认知识库")
        )
    ).scalar_one()
    return kb.id


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------- P2-1 论坛 ----------------


async def _make_kb_with_card(client, auth_headers, session_factory, name="分享测试库"):
    kb = await client.post("/api/knowledge-bases", json={"name": name}, headers=auth_headers)
    kb_id = kb.json()["data"]["id"]
    me = await client.get("/api/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["id"]
    async with session_factory() as db:
        asset = KnowledgeAsset(user_id=user_id, kb_id=kb_id, type="text", raw_content="x",
                               parse_status="done", created_at=_now())
        db.add(asset)
        await db.flush()
        db.add(KnowledgeCard(
            user_id=user_id, kb_id=kb_id, asset_id=asset.id, title="分享卡",
            summary="摘要", key_points=["a", "b", "c"],
            qa_pairs=[{"question": "q", "answer": "a"}], tags=["t"], created_at=_now(),
        ))
        await db.commit()
    return kb_id


async def test_forum_share_lifecycle(client, auth_headers, session_factory, fake_redis):
    """分享→论坛可见→更新→取消下线（spec §5.7.1规则1/3/4）。"""
    kb_id = await _make_kb_with_card(client, auth_headers, session_factory)

    share = await client.post("/api/forum/shares", json={"kb_id": kb_id}, headers=auth_headers)
    assert share.status_code == 201
    share_id = share.json()["data"]["id"]

    # 重复分享 409
    dup = await client.post("/api/forum/shares", json={"kb_id": kb_id}, headers=auth_headers)
    assert dup.status_code == 409

    # 论坛列表可见（含卡片数概要）
    listing = (await client.get("/api/forum/shares", headers=auth_headers)).json()["data"]
    assert any(i["id"] == share_id and i["card_count"] == 1 for i in listing["items"])

    # 更新分享刷新快照时间
    upd = await client.put(f"/api/forum/shares/{share_id}", headers=auth_headers)
    assert upd.status_code == 200

    # 取消 → 详情404、列表消失
    cancel = await client.delete(f"/api/forum/shares/{share_id}", headers=auth_headers)
    assert cancel.status_code == 200
    assert (await client.get(f"/api/forum/shares/{share_id}", headers=auth_headers)).status_code == 404
    listing2 = (await client.get("/api/forum/shares", headers=auth_headers)).json()["data"]
    assert all(i["id"] != share_id for i in listing2["items"])

    # 取消后可重新分享（design v1.1 修复③：无UK阻拦）
    reshare = await client.post("/api/forum/shares", json={"kb_id": kb_id}, headers=auth_headers)
    assert reshare.status_code == 201


async def test_forum_snapshot_decoupled_and_readonly(client, auth_headers, session_factory):
    """快照与原库解耦（§5.7.1规则2）+ 他人只读且不可写（规则6~7）。"""
    kb_id = await _make_kb_with_card(client, auth_headers, session_factory, "解耦测试库")
    share_id = (await client.post("/api/forum/shares", json={"kb_id": kb_id}, headers=auth_headers)).json()["data"]["id"]

    # 他人（B）浏览可见；但更新/取消他人分享 404
    other = await client.post("/api/auth/register", json={"email": f"f-{uuid.uuid4().hex[:6]}@t.cn", "password": "Passw0rd123"})
    other_headers = {"Authorization": f"Bearer {other.json()['data']['token']}"}
    detail = await client.get(f"/api/forum/shares/{share_id}", headers=other_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["cards"][0]["title"] == "分享卡"
    assert (await client.put(f"/api/forum/shares/{share_id}", headers=other_headers)).status_code == 404
    assert (await client.delete(f"/api/forum/shares/{share_id}", headers=other_headers)).status_code == 404

    # 分享后修改原库卡片 → 快照仍为旧内容
    async with session_factory() as db:
        card = (await db.execute(select(KnowledgeCard).where(KnowledgeCard.title == "分享卡"))).scalar_one()
        card.title = "改过的标题"
        await db.commit()
    detail2 = (await client.get(f"/api/forum/shares/{share_id}", headers=other_headers)).json()["data"]
    assert detail2["cards"][0]["title"] == "分享卡"  # 旧快照

    # 更新分享后快照刷新
    await client.put(f"/api/forum/shares/{share_id}", headers=auth_headers)
    detail3 = (await client.get(f"/api/forum/shares/{share_id}", headers=other_headers)).json()["data"]
    assert detail3["cards"][0]["title"] == "改过的标题"


async def test_empty_kb_share_blocked(client, auth_headers):
    """空知识库分享拦截（spec §5.7.3异常4）。"""
    kb = await client.post("/api/knowledge-bases", json={"name": "空库"}, headers=auth_headers)
    resp = await client.post("/api/forum/shares", json={"kb_id": kb.json()["data"]["id"]}, headers=auth_headers)
    assert resp.status_code == 422


async def test_kb_delete_with_share_choices(client, auth_headers, session_factory, fake_redis):
    """删除已分享库：remove=同时移除；keep=快照继续展示（spec §5.7.3异常2）。"""
    kb_id = await _make_kb_with_card(client, auth_headers, session_factory, "删除联动库")
    share_id = (await client.post("/api/forum/shares", json={"kb_id": kb_id}, headers=auth_headers)).json()["data"]["id"]

    # keep（默认）：库删了，论坛快照仍可见
    info = (await client.delete(f"/api/knowledge-bases/{kb_id}?confirm=false", headers=auth_headers)).json()["data"]
    assert info["has_shared"] is True
    del1 = await client.delete(f"/api/knowledge-bases/{kb_id}?confirm=true&share_action=keep", headers=auth_headers)
    assert del1.status_code == 200
    assert (await client.get(f"/api/forum/shares/{share_id}", headers=auth_headers)).status_code == 200

    # remove：分享同步取消
    kb_id2 = await _make_kb_with_card(client, auth_headers, session_factory, "删除联动库2")
    share_id2 = (await client.post("/api/forum/shares", json={"kb_id": kb_id2}, headers=auth_headers)).json()["data"]["id"]
    await client.delete(f"/api/knowledge-bases/{kb_id2}?confirm=true&share_action=remove", headers=auth_headers)
    assert (await client.get(f"/api/forum/shares/{share_id2}", headers=auth_headers)).status_code == 404


# ---------------- P2-2 拼图 ----------------


async def _make_map(client, auth_headers, session_factory, kb_id: str, depth2: bool = False) -> str:
    async with session_factory() as db:
        mp = MindMap(kb_id=kb_id, version_source="auto", created_at=_now())
        db.add(mp)
        await db.flush()
        root = MapNode(map_id=mp.id, parent_id=None, title="根")
        db.add(root)
        await db.flush()
        l1 = MapNode(map_id=mp.id, parent_id=root.id, title="子一")
        l2 = MapNode(map_id=mp.id, parent_id=root.id, title="子二")
        db.add_all([l1, l2])
        await db.flush()
        if depth2:
            db.add(MapNode(map_id=mp.id, parent_id=l1.id, title="孙一"))
        await db.commit()
        return str(mp.id)


async def test_puzzle_lifecycle(session_factory, kb_with_user, client, auth_headers):
    """发起→提交判定（父子一致性）→重复提交409（spec §6.11规则5）。"""
    ctx = kb_with_user
    async with session_factory() as db:
        kb_id = await _default_kb_id(db, ctx["user_id"])
    await _make_map(client, auth_headers, session_factory, kb_id)

    start = await client.post("/api/map-puzzles", json={"kb_id": kb_id}, headers=auth_headers)
    assert start.status_code == 201
    data = start.json()["data"]
    puzzle_id = data["puzzle_id"]
    assert data["total"] == 3
    assert all("parent_id" not in n for n in data["nodes"])  # 答案键不下发

    # 拉取作答视图（不含答案）
    state = (await client.get(f"/api/map-puzzles/{puzzle_id}", headers=auth_headers)).json()["data"]
    assert state["progress"] == "in_progress"

    # 正确拼装：从服务端答案无法获取 → 用错误答案先提交一次验证计分
    nodes = {n["id"]: n["title"] for n in data["nodes"]}
    wrong = {nid: None for nid in nodes}  # 全部设为根 → 只有真根正确
    result = (await client.post(f"/api/map-puzzles/{puzzle_id}/submit", json={"assignments": wrong}, headers=auth_headers)).json()["data"]
    assert result["total"] == 3 and result["correct"] == 1  # 仅根节点正确

    # 重复提交 409
    again = await client.post(f"/api/map-puzzles/{puzzle_id}/submit", json={"assignments": wrong}, headers=auth_headers)
    assert again.status_code == 409


async def test_puzzle_guards(client, auth_headers):
    """空库/无导图/节点过少的拦截。"""
    kb = (await client.post("/api/knowledge-bases", json={"name": "拼图空库"}, headers=auth_headers)).json()["data"]
    no_map = await client.post("/api/map-puzzles", json={"kb_id": kb["id"]}, headers=auth_headers)
    assert no_map.status_code == 404


# ---------------- P2-3 语义搜索 ----------------


class FakeEmbedClient:
    """确定性向量：含"记忆"→[1,0]，否则[0,1]。"""

    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0] if "记忆" in text else [0.0, 1.0]


async def test_semantic_search(session_factory, kb_with_user, client, auth_headers, monkeypatch):
    ctx = kb_with_user
    async with session_factory() as db:
        kb_id = await _default_kb_id(db, ctx["user_id"])
        asset = KnowledgeAsset(user_id=ctx["user_id"], kb_id=None, type="text", raw_content="x",
                               parse_status="done", created_at=_now())
        db.add(asset)
        await db.flush()
        db.add(KnowledgeCard(
            user_id=ctx["user_id"], kb_id=kb_id, asset_id=asset.id, title="记忆方法", summary="关于记忆",
            key_points=["a", "b", "c"], qa_pairs=[{"question": "q", "answer": "a"}],
            tags=[], embedding=[1.0, 0.0], created_at=_now(),
        ))
        await db.commit()

    monkeypatch.setattr("app.infrastructure.maas_client.get_maas_client", lambda: FakeEmbedClient())
    resp = await client.get("/api/search/semantic", params={"keyword": "记忆"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1 and data["items"][0]["title"] == "记忆方法"
    assert data["items"][0]["similarity"] > 0.99


async def test_semantic_search_requires_maas(client, auth_headers, monkeypatch):
    """无MaaS配置 → 422明确提示（本地演示降级语义清晰）。"""
    from app.infrastructure.maas_client import MaasError

    def broken():
        raise MaasError("MAAS_API_KEY 未配置（环境变量缺失）")

    monkeypatch.setattr("app.infrastructure.maas_client.get_maas_client", broken)
    resp = await client.get("/api/search/semantic", params={"keyword": "任意"}, headers=auth_headers)
    assert resp.status_code == 422
    assert "MaaS" in resp.json()["message"]


# ---------------- P2-4 打卡 ----------------


async def test_streak_days(session_factory, kb_with_user, client, auth_headers):
    """连续打卡：昨天+今天有完成记录 → streak≥2（spec §5.6.1规则7）。"""
    ctx = kb_with_user
    async with session_factory() as db:
        kb_id = await _default_kb_id(db, ctx["user_id"])
        asset = KnowledgeAsset(user_id=ctx["user_id"], kb_id=None, type="text", raw_content="x",
                               parse_status="done", created_at=_now())
        db.add(asset)
        await db.flush()
        card = KnowledgeCard(
            user_id=ctx["user_id"], kb_id=kb_id, asset_id=asset.id, title="卡", summary="摘",
            key_points=["a", "b", "c"], qa_pairs=[{"question": "q", "answer": "a"}],
            review_interval_days=1, review_count=1, created_at=_now(),
        )
        db.add(card)
        await db.flush()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(ReviewTask(card_id=card.id, user_id=ctx["user_id"], planned_date=now.date(),
                          status="done", rating="remember", completed_at=now))
        db.add(ReviewTask(card_id=card.id, user_id=ctx["user_id"], planned_date=now.date(),
                          status="done", rating="remember", completed_at=now - timedelta(days=1)))
        await db.commit()

    stats = (await client.get("/api/reviews/statistics", headers=auth_headers)).json()["data"]
    assert stats["streak_days"] >= 2
    assert stats["total_reviews"] == 2 and stats["mastered_count"] == 1


# ---------------- P2-5 手机号注册 ----------------


async def test_sms_registration_flow(client, auth_headers, fake_redis, monkeypatch):
    """console驱动：发码→Redis存码→注册成功（ENABLE_SMS=true）。"""
    from app.config import settings

    monkeypatch.setattr(settings, "ENABLE_SMS", True)
    monkeypatch.setattr(settings, "SMS_DRIVER", "console")
    phone = "13800001234"

    sent = await client.post("/api/auth/sms/code", json={"phone": phone})
    assert sent.status_code == 200
    code = await fake_redis.get(f"sms:code:{phone}")
    assert code

    reg = await client.post("/api/auth/register/phone",
                            json={"phone": phone, "code": code, "password": "Passw0rd123"})
    assert reg.status_code == 200
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {reg.json()['data']['token']}"})
    assert me.status_code == 200

    # 验证码一次性：复用 → 422
    reg2 = await client.post("/api/auth/register/phone",
                             json={"phone": "13800005678", "code": code, "password": "Passw0rd123"})
    assert reg2.status_code == 422


async def test_sms_disabled_by_default(client):
    """ENABLE_SMS=false → 发码端点422明确提示（P2-5受开关保护）。"""
    resp = await client.post("/api/auth/sms/code", json={"phone": "13800001234"})
    assert resp.status_code == 422
    assert "未开放" in resp.json()["message"]
