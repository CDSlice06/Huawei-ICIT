"""思维导图服务（tasks.md 7.1/7.2，spec §5.5.1）。"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms.map_validate import MapValidationError, validate_map_tree
from app.infrastructure.maas_client import get_maas_client
from app.infrastructure.prompts import MAP_SYSTEM_PROMPT, MAP_USER_TEMPLATE
from app.models import AsyncTask, KnowledgeCard, MapNode, MindMap


class MapValidationError2(Exception):
    """导图生成业务校验失败。"""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def create_map_gen_task(db: AsyncSession, user_id: str, kb_id: str) -> AsyncTask:
    """创建导图生成异步任务（MaaS层级提炼耗时30s+，走异步链，tasks.md 决策记录4）。"""
    task = AsyncTask(
        user_id=user_id,
        type="map_gen",
        ref_id=kb_id,
        status="pending",
        created_at=_now(),
    )
    db.add(task)
    await db.commit()
    return task


async def map_gen_task_handler(db: AsyncSession, task: AsyncTask) -> dict:
    """map_gen 真实 handler（tasks.md 7.1）。

    前置校验：空库直接任务失败；读取全部卡片→MaaS层级JSON→权威校验→持久化。
    失败保留旧导图并标记失败（spec §5.5.3异常1）。
    """
    kb_id = task.ref_id

    cards_result = await db.execute(
        select(KnowledgeCard).where(KnowledgeCard.kb_id == kb_id).order_by(KnowledgeCard.created_at.asc())
    )
    cards = list(cards_result.scalars().all())
    if not cards:
        raise MapValidationError2("该知识库暂无知识卡片，请先导入素材")

    cards_json = [
        {
            "card_id": str(c.id),
            "title": c.title,
            "summary": c.summary,
            "key_points": c.key_points,
        }
        for c in cards
    ]
    valid_card_ids = {str(c.id) for c in cards}

    client = get_maas_client()
    raw = await client.chat_json(
        [
            {"role": "system", "content": MAP_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": MAP_USER_TEMPLATE.format(kb_name=kb_id, cards_json=str(cards_json)),
            },
        ]
    )

    # 后端权威校验（根唯一/无环语义/card_id合法/非叶不挂卡）
    try:
        flat_nodes = validate_map_tree(raw, valid_card_ids)
    except MapValidationError as exc:
        raise MapValidationError2(f"导图结构校验失败: {exc}") from exc

    # 持久化：一库一图，覆盖旧图（spec §5.5.1规则5重建语义）
    old_map_result = await db.execute(select(MindMap).where(MindMap.kb_id == kb_id))
    old_map = old_map_result.scalar_one_or_none()
    if old_map is not None:
        nodes_result = await db.execute(select(MapNode).where(MapNode.map_id == old_map.id))
        for node in nodes_result.scalars().all():
            await db.delete(node)
        await db.delete(old_map)
        await db.flush()

    new_map = MindMap(kb_id=kb_id, version_source="auto", created_at=_now())
    db.add(new_map)
    await db.flush()

    key_to_id: dict[str, str] = {}
    for n in flat_nodes:
        node = MapNode(
            map_id=new_map.id,
            parent_id=key_to_id.get(n["parent_key"]) if n["parent_key"] else None,
            title=n["title"],
            card_id=n["card_id"] if n["card_id"] else None,
            pos_x=None,
            pos_y=None,
        )
        db.add(node)
        await db.flush()
        key_to_id[n["key"]] = str(node.id)

    await db.commit()
    return {"map_id": str(new_map.id), "node_count": len(flat_nodes)}


async def get_map_by_kb(db: AsyncSession, user_id: str, kb_id: str) -> dict | None:
    """查询导图（节点树+坐标+版本来源，spec §5.5.1规则2~3）。"""
    from app.services import kb_service

    try:
        await kb_service.get_owned_kb(db, user_id, kb_id)
    except kb_service.KbNotFound:
        return None

    map_result = await db.execute(select(MindMap).where(MindMap.kb_id == kb_id))
    mind_map = map_result.scalar_one_or_none()
    if mind_map is None:
        return None

    nodes_result = await db.execute(select(MapNode).where(MapNode.map_id == mind_map.id))
    nodes = nodes_result.scalars().all()
    return {
        "map_id": str(mind_map.id),
        "kb_id": kb_id,
        "version_source": mind_map.version_source,
        "nodes": [
            {
                "id": str(n.id),
                "parent_id": str(n.parent_id) if n.parent_id else None,
                "title": n.title,
                "card_id": str(n.card_id) if n.card_id else None,
                "pos_x": n.pos_x,
                "pos_y": n.pos_y,
            }
            for n in nodes
        ],
    }