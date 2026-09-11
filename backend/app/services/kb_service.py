"""知识库服务（tasks.md 6.1/6.2，spec §5.4.1、§6.6）。"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure import redis_client
from app.models import AsyncTask, KnowledgeBase, KnowledgeCard, MapNode, MindMap, ReviewTask

KB_NAME_MAX = 50
DEFAULT_KB_NAME = "默认知识库"


class KbNameConflict(Exception):
    """同用户下知识库重名（spec §6.6规则2）。"""


class KbNotFound(Exception):
    """知识库不存在。"""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def create_kb(db: AsyncSession, user_id: str, name: str) -> KnowledgeBase:
    if len(name) > KB_NAME_MAX:
        raise ValueError("名称超过50字符")
    conflict = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.user_id == user_id, KnowledgeBase.name == name)
    )
    if conflict.scalar_one_or_none() is not None:
        raise KbNameConflict()
    kb = KnowledgeBase(user_id=user_id, name=name, created_at=_now())
    db.add(kb)
    await db.commit()
    await _invalidate_kb_cache(user_id)
    return kb


async def get_default_kb(db: AsyncSession, user_id: str) -> KnowledgeBase | None:
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.user_id == user_id, KnowledgeBase.name == DEFAULT_KB_NAME)
    )
    return result.scalar_one_or_none()


async def list_kbs(db: AsyncSession, user_id: str) -> list[dict]:
    """知识库列表（Redis缓存 TTL 5min，spec §5.4.2）。"""
    import json

    key = redis_client.KEY_KB_LIST.format(user_id=user_id)
    cached = await redis_client.cache_get(key)
    if cached:
        return json.loads(cached)

    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.user_id == user_id).order_by(KnowledgeBase.created_at.asc())
    )
    kbs = result.scalars().all()
    items = []
    for kb in kbs:
        card_count = await db.execute(
            select(func.count()).select_from(KnowledgeCard).where(KnowledgeCard.kb_id == kb.id)
        )
        items.append({
            "id": str(kb.id),
            "name": kb.name,
            "card_count": int(card_count.scalar_one() or 0),
            "created_at": str(kb.created_at),
        })
    await redis_client.cache_set(key, json.dumps(items, ensure_ascii=False), ttl=300)
    return items


async def rename_kb(db: AsyncSession, user_id: str, kb_id: str, name: str) -> KnowledgeBase:
    if len(name) > KB_NAME_MAX:
        raise ValueError("名称超过50字符")
    kb = await get_owned_kb(db, user_id, kb_id)
    conflict = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.user_id == user_id, KnowledgeBase.name == name, KnowledgeBase.id != kb_id
        )
    )
    if conflict.scalar_one_or_none() is not None:
        raise KbNameConflict()
    kb.name = name
    await db.commit()
    await _invalidate_kb_cache(user_id)
    return kb


async def get_owned_kb(db: AsyncSession, user_id: str, kb_id: str) -> KnowledgeBase:
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if kb is None or kb.user_id != user_id:
        raise KbNotFound()
    return kb


async def count_cards(db: AsyncSession, kb_id: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(KnowledgeCard).where(KnowledgeCard.kb_id == kb_id)
    )
    return int(result.scalar_one() or 0)


async def count_active_shares(db: AsyncSession, kb_id: str) -> int:
    """统计该库生效中的论坛分享数（spec §5.7.3异常2 删除确认明示用）。"""
    from sqlalchemy import func

    from app.models import SharedKnowledgeBase

    result = await db.execute(
        select(func.count()).select_from(SharedKnowledgeBase).where(
            SharedKnowledgeBase.source_kb_id == kb_id, SharedKnowledgeBase.status == "shared"
        )
    )
    return int(result.scalar_one() or 0)


async def delete_kb(
    db: AsyncSession, user_id: str, kb_id: str, share_action: str = "keep"
) -> int:
    """删除知识库：级联删除卡片+导图+节点+复习任务（spec §5.4.1规则3）。返回级联删除的卡片数。

    share_action（spec §5.7.3异常2/§6.6规则5）：keep=保留论坛快照继续展示；remove=同时移除分享。
    """
    from app.services import forum_service

    kb = await get_owned_kb(db, user_id, kb_id)
    card_count = await count_cards(db, kb_id)
    if share_action == "remove":
        await forum_service.cancel_shares_of_kb(db, kb_id)

    # 级联：复习任务（经由卡片）
    cards_result = await db.execute(select(KnowledgeCard).where(KnowledgeCard.kb_id == kb_id))
    card_ids = [c.id for c in cards_result.scalars().all()]
    if card_ids:
        rt_result = await db.execute(select(ReviewTask).where(ReviewTask.card_id.in_(card_ids)))
        for rt in rt_result.scalars().all():
            await db.delete(rt)

    # 级联：导图与节点
    maps_result = await db.execute(select(MindMap).where(MindMap.kb_id == kb_id))
    for mp in maps_result.scalars().all():
        nodes_result = await db.execute(select(MapNode).where(MapNode.map_id == mp.id))
        for node in nodes_result.scalars().all():
            await db.delete(node)
        await db.delete(mp)

    # 级联：卡片（其关联复习任务已删；素材保留）
    if card_ids:
        cards_result = await db.execute(select(KnowledgeCard).where(KnowledgeCard.kb_id == kb_id))
        for card in cards_result.scalars().all():
            await db.delete(card)

    await db.delete(kb)
    await db.commit()
    await _invalidate_kb_cache(user_id)
    return card_count


async def _invalidate_kb_cache(user_id: str) -> None:
    await redis_client.cache_delete(redis_client.KEY_KB_LIST.format(user_id=user_id))