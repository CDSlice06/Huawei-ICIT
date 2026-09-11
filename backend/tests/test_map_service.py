# -*- coding: utf-8 -*-
"""导图生成 handler 与知识库级联删除测试（tasks.md 7.1/6.1/14.1，mock MaaS）。

map_gen 走异步任务链（决策记录4）：合法层级落库、结构非法/非法card_id失败不落库、
空库任务失败提示正确；知识库删除级联清理卡片+导图+节点+复习任务。
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

import app.services.map_service as map_service
from app.models import (
    AsyncTask,
    KnowledgeBase,
    KnowledgeCard,
    MapNode,
    MindMap,
    ReviewTask,
    User,
)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FakeMaaS:
    def __init__(self, payload: dict):
        self.payload = payload

    async def chat_json(self, messages, **kwargs):
        return self.payload


def _valid_tree(card_id: str) -> dict:
    """合法层级（validate_map_tree 约定顶层为 {"root": {...}}）。"""
    return {
        "root": {
            "title": "根节点",
            "children": [
                {"title": "叶子一", "card_id": card_id, "children": []},
                {"title": "叶子二", "children": []},
            ],
        }
    }


@pytest.fixture
async def kb_with_cards(client, auth_headers, session_factory, fake_redis):
    """预置用户+知识库+2张卡片（用户与auth_headers同一账号，供API级测试）。"""
    me = await client.get("/api/auth/me", headers=auth_headers)
    user_id = me.json()["data"]["id"]
    kb_resp = await client.post("/api/knowledge-bases", json={"name": "导图测试库"}, headers=auth_headers)
    assert kb_resp.status_code == 200
    kb_id = kb_resp.json()["data"]["id"]
    async with session_factory() as db:
        user = User(id=user_id, email=f"map-{datetime.now().timestamp()}@t.cn", password_hash="x", created_at=_now())
        kb = KnowledgeBase(id=kb_id, user_id=user.id, name="导图测试库", created_at=_now())
        card_ids = []
        from app.models import KnowledgeAsset

        for i in range(2):
            asset = KnowledgeAsset(
                user_id=user.id, kb_id=kb.id, type="text",
                raw_content=f"素材{i}", parse_status="done", created_at=_now(),
            )
            db.add(asset)
            await db.flush()
            card = KnowledgeCard(
                user_id=user.id,
                kb_id=kb.id,
                asset_id=asset.id,
                title=f"卡片{i}",
                summary=f"摘要{i}",
                key_points=["a", "b", "c"],
                qa_pairs=[{"question": "q", "answer": "a"}],
                review_interval_days=1,
                review_count=0,
                created_at=_now(),
            )
            db.add(card)
            card_ids.append(card)
        await db.flush()
        result = {"user_id": user.id, "kb_id": kb.id, "card_ids": [str(c.id) for c in card_ids]}
        await db.commit()
    return result


async def test_valid_tree_persisted(session_factory, kb_with_cards, monkeypatch):
    ctx = kb_with_cards
    monkeypatch.setattr(
        map_service, "get_maas_client", lambda: FakeMaaS(_valid_tree(ctx["card_ids"][0]))
    )
    async with session_factory() as db:
        task = AsyncTask(
            user_id=ctx["user_id"], type="map_gen", ref_id=ctx["kb_id"],
            status="pending", created_at=_now(),
        )
        db.add(task)
        await db.commit()
        result = await map_service.map_gen_task_handler(db, task)

    assert task.status == "pending"  # handler 不负责任务状态（TaskRunner管理）
    async with session_factory() as db:
        mp = (
            await db.execute(select(MindMap).where(MindMap.kb_id == ctx["kb_id"]))
        ).scalar_one()
        assert mp.version_source == "auto"
        nodes = (
            await db.execute(select(MapNode).where(MapNode.map_id == mp.id))
        ).scalars().all()
        assert len(nodes) == 3  # 根 + 2叶子
        leaf_cards = {str(n.card_id) for n in nodes if n.card_id}
        assert ctx["card_ids"][0] in leaf_cards
        assert result["node_count"] == 3


async def test_invalid_card_id_fails_without_persist(session_factory, kb_with_cards, monkeypatch):
    """非法card_id（非库内卡片）→ 校验失败，不落库任何导图。"""
    ctx = kb_with_cards
    monkeypatch.setattr(
        map_service, "get_maas_client", lambda: FakeMaaS(_valid_tree("fake-card-id"))
    )
    async with session_factory() as db:
        task = AsyncTask(
            user_id=ctx["user_id"], type="map_gen", ref_id=ctx["kb_id"],
            status="pending", created_at=_now(),
        )
        db.add(task)
        await db.commit()
        with pytest.raises(map_service.MapValidationError2, match="校验失败"):
            await map_service.map_gen_task_handler(db, task)

    async with session_factory() as db:
        maps = (
            await db.execute(select(MindMap).where(MindMap.kb_id == ctx["kb_id"]))
        ).scalars().all()
        assert maps == []


async def test_invalid_structure_rejected(session_factory, kb_with_cards, monkeypatch):
    """结构非法（非叶节点挂卡片/根缺失/标题超长）→ 校验失败不落库。"""
    ctx = kb_with_cards
    cases = [
        # 非叶子节点挂 card_id（spec §6.4规则5）
        {
            "root": {
                "title": "根",
                "children": [
                    {"title": "内部节点", "card_id": ctx["card_ids"][0],
                     "children": [{"title": "叶子", "children": []}]},
                ],
            }
        },
        # 根节点缺失
        {"tree": {}},
        # 叶子标题超过50字符
        {"root": {"title": "根", "children": [{"title": "长" * 51, "children": []}]}},
    ]
    async with session_factory() as db:
        for payload in cases:
            monkeypatch.setattr(map_service, "get_maas_client", lambda: FakeMaaS(payload))
            task = AsyncTask(
                user_id=ctx["user_id"], type="map_gen", ref_id=ctx["kb_id"],
                status="pending", created_at=_now(),
            )
            db.add(task)
            await db.commit()
            with pytest.raises(map_service.MapValidationError2):
                await map_service.map_gen_task_handler(db, task)

    async with session_factory() as db:
        maps = (
            await db.execute(select(MindMap).where(MindMap.kb_id == ctx["kb_id"]))
        ).scalars().all()
        assert maps == []  # 全部失败，未落库


async def test_empty_kb_fails_with_hint(session_factory, kb_with_cards, monkeypatch):
    """空库任务失败并提示先导入素材（spec §5.5.3异常1）。"""
    ctx = kb_with_cards
    monkeypatch.setattr(map_service, "get_maas_client", lambda: FakeMaaS({}))
    async with session_factory() as db:
        task = AsyncTask(
            user_id=ctx["user_id"], type="map_gen", ref_id="empty-kb-id",
            status="pending", created_at=_now(),
        )
        db.add(task)
        await db.commit()
        with pytest.raises(map_service.MapValidationError2, match="暂无知识卡片"):
            await map_service.map_gen_task_handler(db, task)


async def test_regenerate_replaces_old_map(session_factory, kb_with_cards, monkeypatch):
    """一库一图：重新生成覆盖旧图（spec §5.5.1规则5）。"""
    ctx = kb_with_cards
    monkeypatch.setattr(
        map_service, "get_maas_client", lambda: FakeMaaS(_valid_tree(ctx["card_ids"][0]))
    )
    async with session_factory() as db:
        task1 = AsyncTask(
            user_id=ctx["user_id"], type="map_gen", ref_id=ctx["kb_id"],
            status="pending", created_at=_now(),
        )
        db.add(task1)
        await db.commit()
        await map_service.map_gen_task_handler(db, task1)

        task2 = AsyncTask(
            user_id=ctx["user_id"], type="map_gen", ref_id=ctx["kb_id"],
            status="pending", created_at=_now(),
        )
        db.add(task2)
        await db.commit()
        await map_service.map_gen_task_handler(db, task2)

    async with session_factory() as db:
        maps = (
            await db.execute(select(MindMap).where(MindMap.kb_id == ctx["kb_id"]))
        ).scalars().all()
        assert len(maps) == 1  # 旧图被覆盖


async def test_kb_delete_cascades(session_factory, fake_redis):
    """删除知识库级联清理卡片/导图/节点/复习任务（tasks.md 6.1）。"""
    from app.services import kb_service

    async with session_factory() as db:
        user = User(email=f"kbdel-{datetime.now().timestamp()}@t.cn", password_hash="x", created_at=_now())
        db.add(user)
        await db.flush()
        kb = KnowledgeBase(user_id=user.id, name="待删库", created_at=_now())
        db.add(kb)
        await db.flush()
        from app.models import KnowledgeAsset

        asset = KnowledgeAsset(
            user_id=user.id, kb_id=kb.id, type="text",
            raw_content="素材", parse_status="done", created_at=_now(),
        )
        db.add(asset)
        await db.flush()
        card = KnowledgeCard(
            user_id=user.id, kb_id=kb.id, asset_id=asset.id, title="卡", summary="摘",
            key_points=["a", "b", "c"], qa_pairs=[{"question": "q", "answer": "a"}],
            review_interval_days=1, review_count=0, created_at=_now(),
        )
        db.add(card)
        await db.flush()
        db.add(ReviewTask(card_id=card.id, user_id=user.id, planned_date=_now().date(), status="pending"))
        mp = MindMap(kb_id=kb.id, version_source="auto", created_at=_now())
        db.add(mp)
        await db.flush()
        db.add(MapNode(map_id=mp.id, parent_id=None, title="根"))
        await db.commit()
        kb_id, card_id, user_id = kb.id, card.id, user.id

    async with session_factory() as db:
        deleted = await kb_service.delete_kb(db, user_id, kb_id)
        assert deleted == 1

    async with session_factory() as db:
        assert (await db.execute(select(KnowledgeCard).where(KnowledgeCard.id == card_id))).scalar_one_or_none() is None
        assert (await db.execute(select(MindMap).where(MindMap.kb_id == kb_id))).scalars().all() == []
        assert (await db.execute(select(ReviewTask).where(ReviewTask.card_id == card_id))).scalars().all() == []


# ---------------- 手动编辑（P1-6，spec §5.5.1规则4~7、§6.4） ----------------


async def _make_map(session_factory, ctx, with_leaves: bool = True) -> str:
    """为测试库建一张导图：根+2叶子（叶子1挂卡片1）。返回 map_id。"""
    async with session_factory() as db:
        mp = MindMap(kb_id=ctx["kb_id"], version_source="auto", created_at=_now())
        db.add(mp)
        await db.flush()
        root = MapNode(map_id=mp.id, parent_id=None, title="根", pos_x=None, pos_y=None)
        db.add(root)
        await db.flush()
        if with_leaves:
            db.add(MapNode(map_id=mp.id, parent_id=root.id, title="叶子一", card_id=ctx["card_ids"][0]))
            db.add(MapNode(map_id=mp.id, parent_id=root.id, title="叶子二"))
        await db.commit()
        return str(mp.id)


async def test_edit_title_sets_manual_version(session_factory, kb_with_cards, client, auth_headers):
    """编辑节点标题后版本来源置"手动编辑"（spec §6.4规则6）。"""
    ctx = kb_with_cards
    map_id = await _make_map(session_factory, ctx)
    async with session_factory() as db:
        nodes = (await db.execute(select(MapNode).where(MapNode.map_id == map_id))).scalars().all()
        leaf1 = next(n for n in nodes if n.title == "叶子一")

    resp = await client.put(
        f"/api/mind-maps/{ctx['kb_id']}/nodes",
        json={"updates": [{"id": str(leaf1.id), "title": "改名后的叶子"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["version_source"] == "manual"
    assert any(n["title"] == "改名后的叶子" for n in data["nodes"])


async def test_reparent_and_cycle_blocked(session_factory, kb_with_cards, client, auth_headers):
    """合法reparent成功；把自己挂到自己的后代上 → 环拦截422（spec §6.4规则8）。"""
    ctx = kb_with_cards
    map_id = await _make_map(session_factory, ctx)
    async with session_factory() as db:
        nodes = (await db.execute(select(MapNode).where(MapNode.map_id == map_id))).scalars().all()
        by_title = {n.title: n for n in nodes}
        root, leaf1, leaf2 = by_title["根"], by_title["叶子一"], by_title["叶子二"]

    # 合法：叶子二挂到叶子一下（同时清掉叶子一的卡片，使其成为合法非叶节点）
    ok = await client.put(
        f"/api/mind-maps/{ctx['kb_id']}/nodes",
        json={"updates": [
            {"id": str(leaf2.id), "parent_id": str(leaf1.id)},
            {"id": str(leaf1.id), "card_id": None},
        ]},
        headers=auth_headers,
    )
    assert ok.status_code == 200, ok.text

    # 环：叶子一挂到叶子二（此刻叶子二是叶子一的子节点）→ 拦截
    bad = await client.put(
        f"/api/mind-maps/{ctx['kb_id']}/nodes",
        json={"updates": [{"id": str(leaf1.id), "parent_id": str(leaf2.id)}]},
        headers=auth_headers,
    )
    assert bad.status_code == 422
    assert "环" in bad.json()["message"]


async def test_delete_leaf_only_and_additions(session_factory, kb_with_cards, client, auth_headers):
    ctx = kb_with_cards
    map_id = await _make_map(session_factory, ctx)
    async with session_factory() as db:
        nodes = (await db.execute(select(MapNode).where(MapNode.map_id == map_id))).scalars().all()
        by_title = {n.title: n for n in nodes}
        root, leaf2 = by_title["根"], by_title["叶子二"]

    # 删除非叶节点 → 422
    bad = await client.put(
        f"/api/mind-maps/{ctx['kb_id']}/nodes",
        json={"deletions": [str(root.id)]},
        headers=auth_headers,
    )
    assert bad.status_code == 422

    # 新增子节点 + 删除叶子 → 成功
    ok = await client.put(
        f"/api/mind-maps/{ctx['kb_id']}/nodes",
        json={
            "additions": [{"parent_id": str(root.id), "title": "新分组"}],
            "deletions": [str(leaf2.id)],
        },
        headers=auth_headers,
    )
    assert ok.status_code == 200
    titles = {n["title"] for n in ok.json()["data"]["nodes"]}
    assert "新分组" in titles and "叶子二" not in titles


async def test_leaf_card_rules(session_factory, kb_with_cards, client, auth_headers):
    """叶子可挂本库卡片；非叶挂卡/库外卡片 → 422（spec §6.4规则5）。"""
    ctx = kb_with_cards
    map_id = await _make_map(session_factory, ctx)
    async with session_factory() as db:
        nodes = (await db.execute(select(MapNode).where(MapNode.map_id == map_id))).scalars().all()
        root = next(n for n in nodes if n.title == "根")

    bad = await client.put(
        f"/api/mind-maps/{ctx['kb_id']}/nodes",
        json={"updates": [{"id": str(root.id), "card_id": ctx["card_ids"][0]}]},
        headers=auth_headers,
    )
    assert bad.status_code == 422
    assert "非叶子" in bad.json()["message"]

    # 叶子节点脱离父节点成为第二根 → 拦截（根唯一，spec §6.4规则2）
    async with session_factory() as db:
        leaf_nodes = (await db.execute(select(MapNode).where(MapNode.map_id == map_id))).scalars().all()
        leaf2 = next(n for n in leaf_nodes if n.title == "叶子二")
    foreign = await client.put(
        f"/api/mind-maps/{ctx['kb_id']}/nodes",
        json={"updates": [{"id": str(leaf2.id), "parent_id": None}]},
        headers=auth_headers,
    )
    assert foreign.status_code == 422


async def test_position_persist_and_isolation(session_factory, kb_with_cards, client, auth_headers):
    """拖拽位置持久化（spec §6.4规则7）；他人库编辑404。"""
    ctx = kb_with_cards
    map_id = await _make_map(session_factory, ctx)
    async with session_factory() as db:
        nodes = (await db.execute(select(MapNode).where(MapNode.map_id == map_id))).scalars().all()
        root = next(n for n in nodes if n.title == "根")

    ok = await client.put(
        f"/api/mind-maps/{ctx['kb_id']}/nodes",
        json={"updates": [{"id": str(root.id), "pos_x": 120.5, "pos_y": 80.25}]},
        headers=auth_headers,
    )
    assert ok.status_code == 200
    node = next(n for n in ok.json()["data"]["nodes"] if n["title"] == "根")
    assert node["pos_x"] == 120.5 and node["pos_y"] == 80.25

    other = await client.post(
        "/api/auth/register", json={"email": f"me-{uuid.uuid4().hex[:6]}@t.cn", "password": "Passw0rd123"}
    )
    other_headers = {"Authorization": f"Bearer {other.json()['data']['token']}"}
    assert (
        await client.put(
            f"/api/mind-maps/{ctx['kb_id']}/nodes",
            json={"updates": [{"id": str(root.id), "title": "越权"}]},
            headers=other_headers,
        )
    ).status_code == 404
