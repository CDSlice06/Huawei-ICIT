"""知识分享论坛服务（P2-1，spec §5.7、§6.8；design §2.1.3.4）。

发布快照语义：分享/更新分享时一次性序列化卡片+导图(含节点坐标)为JSON，
之后与原库解耦（§5.7.1规则2）；论坛列表走Redis缓存，写操作后失效（§5.7.3异常1）。
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms.map_layout import default_layout
from app.infrastructure import redis_client
from app.models import KnowledgeBase, KnowledgeCard, MapNode, MindMap, SharedKnowledgeBase, User

logger = logging.getLogger(__name__)

FORUM_LIST_CACHE_KEY = "forum:list"
FORUM_LIST_TTL = 60  # 论坛列表缓存1分钟（§5.7.3异常1：取消分享后快速下线）


class KbNotFound(Exception):
    pass


class KbHasNoCards(Exception):
    """空知识库分享拦截（spec §5.7.3异常4）。"""


class ShareConflict(Exception):
    """该库已存在生效中的分享（同一库仅一条shared，design v1.1修复③）。"""


class ShareNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _serialize_snapshot(db: AsyncSession, kb: KnowledgeBase) -> dict:
    """序列化发布快照（design §2.1.3.4：卡片+导图+节点画布坐标）。"""
    cards_result = await db.execute(
        select(KnowledgeCard)
        .where(KnowledgeCard.kb_id == kb.id)
        .order_by(KnowledgeCard.created_at.asc())
    )
    cards = [
        {
            "id": str(c.id),
            "title": c.title,
            "summary": c.summary,
            "key_points": c.key_points,
            "qa": c.qa_pairs,
            "tags": c.tags or [],
        }
        for c in cards_result.scalars().all()
    ]

    mind_maps: list[dict] = []
    map_result = await db.execute(select(MindMap).where(MindMap.kb_id == kb.id))
    mind_map = map_result.scalar_one_or_none()
    if mind_map is not None:
        nodes_result = await db.execute(select(MapNode).where(MapNode.map_id == mind_map.id))
        node_rows = nodes_result.scalars().all()
        flat = [{"id": str(n.id), "parent_id": str(n.parent_id) if n.parent_id else None, "title": n.title} for n in node_rows]
        coords = default_layout(flat)
        nodes = [
            {
                "id": str(n.id),
                "title": n.title,
                "parent_id": str(n.parent_id) if n.parent_id else None,
                "card_id": str(n.card_id) if n.card_id else None,
                "x": (n.pos_x if n.pos_x is not None else coords.get(str(n.id), {}).get("x")),
                "y": (n.pos_y if n.pos_y is not None else coords.get(str(n.id), {}).get("y")),
            }
            for n in node_rows
        ]
        mind_maps.append({
            "id": str(mind_map.id),
            "version_source": mind_map.version_source,
            "nodes": nodes,
        })

    return {
        "kb_name": kb.name,
        "snapshot_time": _now().isoformat(),
        "cards": cards,
        "mind_maps": mind_maps,
    }


async def share_kb(db: AsyncSession, user_id: str, kb_id: str, title: str | None = None) -> SharedKnowledgeBase:
    """分享知识库至论坛（§5.7.1规则1；空库拦截§5.7.3异常4）。"""
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user_id)
    )
    kb = result.scalar_one_or_none()
    if kb is None:
        raise KbNotFound()

    dup = await db.execute(
        select(SharedKnowledgeBase).where(
            SharedKnowledgeBase.user_id == user_id,
            SharedKnowledgeBase.source_kb_id == kb_id,
            SharedKnowledgeBase.status == "shared",
        )
    )
    if dup.scalar_one_or_none() is not None:
        raise ShareConflict()

    snapshot = await _serialize_snapshot(db, kb)
    if not snapshot["cards"]:
        raise KbHasNoCards()

    record = SharedKnowledgeBase(
        user_id=user_id,
        source_kb_id=kb_id,
        snapshot_title=(title or kb.name)[:50],
        snapshot_content=snapshot,
        status="shared",
        shared_at=_now(),
        updated_at=_now(),
    )
    db.add(record)
    await db.commit()
    await redis_client.cache_delete(FORUM_LIST_CACHE_KEY)
    logger.info("forum:share", extra={"user_id": user_id, "share_id": str(record.id)})
    return record


async def list_shares(db: AsyncSession, limit: int = 50) -> list[dict]:
    """论坛列表（全体登录用户可见，仅status=shared，spec §5.7.1规则5）。Redis缓存。"""
    cached = await redis_client.cache_get(FORUM_LIST_CACHE_KEY)
    if cached:
        import json

        return json.loads(cached)

    result = await db.execute(
        select(SharedKnowledgeBase, User.email)
        .join(User, SharedKnowledgeBase.user_id == User.id)
        .where(SharedKnowledgeBase.status == "shared")
        .order_by(SharedKnowledgeBase.shared_at.desc())
        .limit(limit)
    )
    items = [
        {
            "id": str(share.id),
            "title": share.snapshot_title,
            "sharer_email": email,
            "card_count": len((share.snapshot_content or {}).get("cards", [])),
            "shared_at": str(share.shared_at),
            "updated_at": str(share.updated_at),
        }
        for share, email in result.all()
    ]
    import json

    await redis_client.cache_set(FORUM_LIST_CACHE_KEY, json.dumps(items, ensure_ascii=False), ttl=FORUM_LIST_TTL)
    return items


async def list_mine(db: AsyncSession, user_id: str) -> list[dict]:
    """我的分享（含已取消，供管理：更新/取消，spec §5.7.1规则3~4）。"""
    result = await db.execute(
        select(SharedKnowledgeBase)
        .where(SharedKnowledgeBase.user_id == user_id)
        .order_by(SharedKnowledgeBase.shared_at.desc())
    )
    return [
        {
            "id": str(s.id),
            "source_kb_id": str(s.source_kb_id),
            "title": s.snapshot_title,
            "status": s.status,
            "card_count": len((s.snapshot_content or {}).get("cards", [])),
            "shared_at": str(s.shared_at),
            "updated_at": str(s.updated_at),
        }
        for s in result.scalars().all()
    ]


async def get_share_detail(db: AsyncSession, share_id: str) -> dict | None:
    """分享详情（只读快照；已取消的对全体不可见，spec §5.7.1规则4）。"""
    result = await db.execute(select(SharedKnowledgeBase).where(SharedKnowledgeBase.id == share_id))
    share = result.scalar_one_or_none()
    if share is None or share.status != "shared":
        return None
    sharer = await db.execute(select(User.email).where(User.id == share.user_id))
    email = sharer.scalar_one_or_none()
    content = share.snapshot_content or {}
    return {
        "id": str(share.id),
        "title": share.snapshot_title,
        "sharer_email": email,
        "kb_name": content.get("kb_name"),
        "cards": content.get("cards", []),
        "mind_maps": content.get("mind_maps", []),
        "shared_at": str(share.shared_at),
        "updated_at": str(share.updated_at),
    }


async def update_share(db: AsyncSession, share_id: str, user_id: str) -> SharedKnowledgeBase:
    """更新分享：重新序列化当前库内容覆盖旧快照（spec §5.7.1规则3）。"""
    result = await db.execute(select(SharedKnowledgeBase).where(SharedKnowledgeBase.id == share_id))
    share = result.scalar_one_or_none()
    if share is None or share.user_id != user_id:
        raise ShareNotFound()
    if share.status != "shared":
        raise ShareNotFound()

    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == share.source_kb_id))
    kb = kb_result.scalar_one_or_none()
    if kb is None:
        # 原库已删（保留快照模式）→ 无法重新序列化
        raise ShareNotFound()
    share.snapshot_content = await _serialize_snapshot(db, kb)
    share.updated_at = _now()
    await db.commit()
    await redis_client.cache_delete(FORUM_LIST_CACHE_KEY)
    return share


async def cancel_share(db: AsyncSession, share_id: str, user_id: str) -> None:
    """取消分享：置已取消（快照数据保留供历史），论坛即时下线（spec §5.7.1规则4）。"""
    result = await db.execute(select(SharedKnowledgeBase).where(SharedKnowledgeBase.id == share_id))
    share = result.scalar_one_or_none()
    if share is None or share.user_id != user_id:
        raise ShareNotFound()
    if share.status != "shared":
        raise ShareNotFound()
    share.status = "cancelled"
    share.updated_at = _now()
    await db.commit()
    await redis_client.cache_delete(FORUM_LIST_CACHE_KEY)


async def cancel_shares_of_kb(db: AsyncSession, kb_id: str) -> int:
    """删除知识库时"同时移除分享"选项（spec §5.7.3异常2、§6.6规则5）。"""
    result = await db.execute(
        select(SharedKnowledgeBase).where(
            SharedKnowledgeBase.source_kb_id == kb_id, SharedKnowledgeBase.status == "shared"
        )
    )
    shares = result.scalars().all()
    for s in shares:
        s.status = "cancelled"
        s.updated_at = _now()
    if shares:
        await db.commit()
        await redis_client.cache_delete(FORUM_LIST_CACHE_KEY)
    return len(shares)
