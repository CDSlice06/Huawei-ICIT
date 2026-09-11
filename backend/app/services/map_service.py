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


# ---------------- 手动编辑（P1-6，spec §5.5.1规则4~7、§6.4） ----------------

MAX_NODES = 300
MAX_DEPTH = 8


class MapNotFound(Exception):
    """导图不存在（该库尚未生成导图）。"""


class NodeRuleError(Exception):
    """节点编辑违反结构约束（spec §6.4、§5.5.3异常4 环拦截）。"""


async def update_map_nodes(db: AsyncSession, user_id: str, kb_id: str, payload: dict) -> None:
    """批量编辑节点（标题/父子关系/画布位置/关联卡片 + 增删节点），单事务提交。

    编辑后版本来源置为"手动编辑"（spec §6.4规则6）；
    任何结构变更后执行完整性校验：根唯一、无环/无孤儿、非叶不挂卡（spec §6.4规则8）。
    """
    from app.services import kb_service

    try:
        await kb_service.get_owned_kb(db, user_id, kb_id)
    except kb_service.KbNotFound:
        raise MapNotFound()

    map_result = await db.execute(select(MindMap).where(MindMap.kb_id == kb_id))
    mind_map = map_result.scalar_one_or_none()
    if mind_map is None:
        raise MapNotFound()

    nodes_result = await db.execute(select(MapNode).where(MapNode.map_id == mind_map.id))
    nodes: dict[str, MapNode] = {str(n.id): n for n in nodes_result.scalars().all()}
    if not nodes:
        raise NodeRuleError("导图为空，请先生成导图")

    updates = payload.get("updates") or []
    additions = payload.get("additions") or []
    deletions = [str(d) for d in (payload.get("deletions") or [])]

    # 本库有效卡片集合（叶子关联校验用）
    cards_result = await db.execute(
        select(KnowledgeCard.id).where(KnowledgeCard.kb_id == kb_id)
    )
    valid_card_ids = {str(cid) for (cid,) in cards_result.all()}

    # 1) 删除：仅叶子节点（避免孤儿，spec §6.4规则4）
    for nid in deletions:
        node = nodes.get(nid)
        if node is None:
            raise NodeRuleError(f"节点 {nid} 不存在")
        has_children = any(str(n.parent_id) == nid for n in nodes.values() if n.id != node.id)
        if has_children:
            raise NodeRuleError("仅允许删除叶子节点，请先处理其子节点")
        await db.delete(node)
        nodes.pop(nid, None)

    # 2) 新增子节点
    for item in additions:
        title = (item.get("title") or "").strip()
        if not title or len(title) > 50:
            raise NodeRuleError("新增节点标题必填且不超过50字符")
        parent_id = item.get("parent_id")
        if parent_id and str(parent_id) not in nodes:
            raise NodeRuleError("新增节点的父节点不存在")
        card_id = item.get("card_id")
        if card_id:
            card_id = str(card_id)
            if card_id not in valid_card_ids:
                raise NodeRuleError("叶子节点引用了库外卡片")
        node = MapNode(
            map_id=mind_map.id,
            parent_id=parent_id,
            title=title,
            card_id=card_id or None,
            pos_x=item.get("pos_x"),
            pos_y=item.get("pos_y"),
        )
        db.add(node)
        await db.flush()
        nodes[str(node.id)] = node

    # 3) 更新：标题 / 父子关系（环检测）/ 位置 / 关联卡片
    edges = {nid: (str(n.parent_id) if n.parent_id else None) for nid, n in nodes.items()}
    for item in updates:
        nid = str(item.get("id") or "")
        node = nodes.get(nid)
        if node is None:
            raise NodeRuleError(f"节点 {nid} 不存在")
        if "title" in item and item["title"] is not None:
            title = str(item["title"]).strip()
            if not title or len(title) > 50:
                raise NodeRuleError("节点标题必填且不超过50字符")
            node.title = title
        if "parent_id" in item:
            new_parent = str(item["parent_id"]) if item["parent_id"] else None
            if new_parent == nid:
                raise NodeRuleError("不能将节点设为自己的父节点")
            if new_parent is not None and new_parent not in nodes:
                raise NodeRuleError("目标父节点不存在")
            old_parent = edges.get(nid)
            if new_parent != old_parent:
                if new_parent is None:
                    raise NodeRuleError("根节点唯一，不接受新的根节点（spec §6.4规则2）")
                # DFS环检测：新父节点不能在node子树中（spec §6.4规则8）
                from app.algorithms.map_validate import detect_cycle

                trial = dict(edges)
                trial[nid] = new_parent
                if detect_cycle({k: v for k, v in trial.items() if v}, nid, new_parent):
                    raise NodeRuleError("该编排会形成环状引用，已拦截")
                node.parent_id = new_parent
                edges[nid] = new_parent
        if "pos_x" in item or "pos_y" in item:
            node.pos_x = item.get("pos_x") if "pos_x" in item else node.pos_x
            node.pos_y = item.get("pos_y") if "pos_y" in item else node.pos_y
        if "card_id" in item:
            card_id = str(item["card_id"]) if item["card_id"] else None
            if card_id and card_id not in valid_card_ids:
                raise NodeRuleError("叶子节点引用了库外卡片")
            node.card_id = card_id

    # 4) 全树完整性校验：根唯一、无环/无孤儿、非叶不挂卡、规模上限
    validate_tree_integrity(list(nodes.values()))

    mind_map.version_source = "manual"
    await db.commit()


def validate_tree_integrity(nodes: list[MapNode]) -> None:
    """导图结构权威校验（spec §6.4规则2/4/5/8、§5.5.3异常4）。"""
    if len(nodes) > MAX_NODES:
        raise NodeRuleError("导图节点数超出上限")
    children: dict[str | None, list[str]] = {}
    by_id: dict[str, MapNode] = {}
    roots = 0
    for n in nodes:
        by_id[str(n.id)] = n
        parent = str(n.parent_id) if n.parent_id else None
        if parent is None:
            roots += 1
        children.setdefault(parent, []).append(str(n.id))
    if roots != 1:
        raise NodeRuleError("导图必须有且仅有一个根节点")
    root_id = children[None][0]
    # 从根遍历：不可达节点 → 孤儿或环
    seen: set[str] = set()
    depth: dict[str, int] = {root_id: 1}
    stack = [root_id]
    while stack:
        cur = stack.pop()
        seen.add(cur)
        for child in children.get(cur, []):
            if child in seen:
                raise NodeRuleError("导图存在环状引用")
            depth[child] = depth.get(cur, 1) + 1
            stack.append(child)
    unreachable = set(by_id) - seen
    if unreachable:
        raise NodeRuleError("存在未挂接到根节点的节点")
    if max(depth.values(), default=1) > MAX_DEPTH:
        raise NodeRuleError("导图层级过深")
    # 非叶节点不挂卡（spec §6.4规则5）
    for n in nodes:
        if n.card_id and str(n.id) in children and children.get(str(n.id)):
            raise NodeRuleError(f"非叶子节点不应关联卡片: {n.title[:20]}")