# -*- coding: utf-8 -*-
"""知识搜索与标签聚合测试（P1-4/P1-5，spec §5.4.1规则4/6）。

SQLite兼容层跑LIKE降级路径；MySQL FTS ngram路径由方言分支保证同一业务语义，
正式检索效果须在MySQL 8容器复核（tasks.md 14.1注记）。
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import KnowledgeAsset, KnowledgeBase, KnowledgeCard, MistakeEntry
from app.services import search_service
from app.services.search_service import SearchValidationError, _snippet


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _default_kb_id(db, user_id: str) -> str:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.user_id == user_id, KnowledgeBase.name == "默认知识库")
        )
    ).scalar_one()
    return kb.id


async def _make_asset(db, user_id: str) -> str:
    asset = KnowledgeAsset(
        user_id=user_id, kb_id=None, type="text", raw_content="素材",
        parse_status="done", created_at=_now(),
    )
    db.add(asset)
    await db.flush()
    return asset.id


async def _seed(db, user_id: str):
    kb_id = await _default_kb_id(db, user_id)
    asset_id = await _make_asset(db, user_id)
    db.add_all([
        KnowledgeCard(
            user_id=user_id, kb_id=kb_id, asset_id=asset_id, title="遗忘曲线原理", summary="艾宾浩斯遗忘曲线说明记忆衰减规律",
            key_points=["要点"], qa_pairs=[{"question": "q", "answer": "a"}], tags=["记忆"],
            created_at=_now(),
        ),
        KnowledgeCard(
            user_id=user_id, kb_id=kb_id, asset_id=asset_id, title="Python列表", summary="列表与元组的区别",
            key_points=["要点"], qa_pairs=[{"question": "q", "answer": "a"}], tags=["编程"],
            created_at=_now(),
        ),
        KnowledgeAsset(
            user_id=user_id, kb_id=None, type="text", raw_content="原始记录",
            extracted_text="文中提到了艾宾浩斯遗忘曲线的实验方法", parse_status="done", created_at=_now(),
        ),
        MistakeEntry(
            user_id=user_id, question="遗忘曲线是谁提出的？", answer="艾宾浩斯",
            error_analysis="记忆混淆", tags=["记忆"], source_type="text",
            parse_status="done", created_at=_now(),
        ),
        MistakeEntry(
            user_id=user_id, question="未解析条目遗忘曲线", answer="答", error_analysis="析",
            tags=[], source_type="text", parse_status="parsing", created_at=_now(),
        ),
    ])
    await db.commit()


async def test_search_hits_three_types(session_factory, kb_with_user, client, auth_headers):
    ctx = kb_with_user
    async with session_factory() as db:
        await _seed(db, ctx["user_id"])

    resp = await client.get("/api/search", params={"keyword": "艾宾浩斯"}, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["counts"]["cards"] == 1  # 标题/摘要命中
    assert "艾宾浩斯" in data["cards"][0]["snippet"]
    assert data["counts"]["assets"] == 1
    assert data["counts"]["mistakes"] == 1  # parsing条目不参与检索（§5.8.1规则3b）


async def test_search_keyword_in_snippet_only(session_factory, kb_with_user, client, auth_headers):
    """关键词仅在正文/解析字段命中也能检出（标题无关）。"""
    ctx = kb_with_user
    async with session_factory() as db:
        await _seed(db, ctx["user_id"])

    resp = await client.get("/api/search", params={"keyword": "混淆"}, headers=auth_headers)
    data = resp.json()["data"]
    assert data["counts"]["mistakes"] == 1
    assert data["counts"]["cards"] == 0


async def test_search_isolation(client, auth_headers):
    """他人数据不出现在搜索结果（spec §4.3.2）。"""
    resp = await client.get("/api/search", params={"keyword": "艾宾浩斯"}, headers=auth_headers)
    data = resp.json()["data"]
    assert data["counts"]["cards"] == 0 and data["counts"]["mistakes"] == 0


async def test_search_validation(client, auth_headers):
    assert (await client.get("/api/search", params={"keyword": "  "}, headers=auth_headers)).status_code == 422
    resp = await client.get("/api/search", params={"keyword": "长" * 101}, headers=auth_headers)
    assert resp.status_code == 422
    resp = await client.get("/api/search", params={"keyword": "abc", "type": "ghost"}, headers=auth_headers)
    assert resp.status_code == 422


async def test_snippet_window():
    text = "前" * 100 + "关键词" + "后" * 100
    s = _snippet(text, "关键词", radius=10)
    assert s.startswith("…") and s.endswith("…")
    assert "关键词" in s
    # 无命中时返回开头
    assert _snippet("普通文本", "不存在").startswith("普通文本")


async def test_tags_aggregation(session_factory, kb_with_user, client, auth_headers):
    ctx = kb_with_user
    async with session_factory() as db:
        kb_id = await _default_kb_id(db, ctx["user_id"])
        asset_id = await _make_asset(db, ctx["user_id"])
        for i in range(3):
            db.add(KnowledgeCard(
                user_id=ctx["user_id"], kb_id=kb_id, asset_id=asset_id, title=f"卡{i}", summary="摘",
                key_points=["a", "b", "c"], qa_pairs=[{"question": "q", "answer": "a"}],
                tags=["记忆" if i < 2 else "编程"], created_at=_now(),
            ))
        await db.commit()

    resp = await client.get("/api/tags", headers=auth_headers)
    items = resp.json()["data"]["items"]
    by_tag = {t["tag"]: t["count"] for t in items}
    assert by_tag["记忆"] == 2 and by_tag["编程"] == 1
    # 按次数排序
    assert items[0]["count"] >= items[-1]["count"]
