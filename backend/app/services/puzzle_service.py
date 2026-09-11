"""导图拼图自测服务（P2-2，spec §5.5.1规则8~10、§6.11；design §2.4.4）。

固定布局、逐层拼装简化模式（spec备注：不做自由画布打散）：
- 发起：按原导图结构生成打散快照（节点列表+父子答案键，答案键仅存服务端）
- 作答：用户为每个非根节点指定父节点、指定根节点，逐层拼装
- 判定：拼装结果与原导图父子关系的一致性（正确节点数/总节点数）
"""
import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeBase, MapNode, MapPuzzleRecord, MindMap


class PuzzleKbNotFound(Exception):
    pass


class PuzzleMapMissing(Exception):
    """该库尚未生成导图。"""


class PuzzleTooSmall(Exception):
    """导图节点过少，无法拼图（至少2个节点）。"""


class PuzzleNotFound(Exception):
    pass


class PuzzleAlreadyDone(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def create_puzzle(db: AsyncSession, user_id: str, kb_id: str) -> dict:
    """发起拼图自测：打散快照落库，返回仅含节点标题的作答视图。"""
    kb_result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user_id)
    )
    if kb_result.scalar_one_or_none() is None:
        raise PuzzleKbNotFound()

    map_result = await db.execute(select(MindMap).where(MindMap.kb_id == kb_id))
    mind_map = map_result.scalar_one_or_none()
    if mind_map is None:
        raise PuzzleMapMissing()

    nodes_result = await db.execute(select(MapNode).where(MapNode.map_id == mind_map.id))
    nodes = nodes_result.scalars().all()
    if len(nodes) < 2:
        raise PuzzleTooSmall()

    root = next(n for n in nodes if n.parent_id is None)
    answer = {str(n.id): (str(n.parent_id) if n.parent_id else None) for n in nodes}
    view_nodes = [{"id": str(n.id), "title": n.title} for n in nodes]
    random.shuffle(view_nodes)

    record = MapPuzzleRecord(
        user_id=user_id,
        kb_id=kb_id,
        map_id=mind_map.id,
        snapshot={
            "nodes": view_nodes,
            "answer": answer,
            "root_id": str(root.id),
        },
        progress="in_progress",
        started_at=_now(),
    )
    db.add(record)
    await db.commit()
    return {
        "puzzle_id": str(record.id),
        "nodes": view_nodes,
        "total": len(view_nodes),
        "started_at": str(record.started_at),
    }


async def get_puzzle(db: AsyncSession, puzzle_id: str, user_id: str) -> dict | None:
    """作答视图（不含答案键；已完成记录返回结果）。"""
    result = await db.execute(select(MapPuzzleRecord).where(MapPuzzleRecord.id == puzzle_id))
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        return None
    snapshot = record.snapshot or {}
    data = {
        "puzzle_id": str(record.id),
        "kb_id": str(record.kb_id),
        "progress": record.progress,
        "total": len(snapshot.get("nodes", [])),
        "nodes": snapshot.get("nodes", []),
        "started_at": str(record.started_at),
        "result": record.result,
        "completed_at": str(record.completed_at) if record.completed_at else None,
    }
    return data


async def submit_puzzle(
    db: AsyncSession, puzzle_id: str, user_id: str, assignments: dict[str, str | None]
) -> dict:
    """提交拼装结果并判定（spec §6.11规则5：正确拼装节点数与总节点数）。"""
    result = await db.execute(select(MapPuzzleRecord).where(MapPuzzleRecord.id == puzzle_id))
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        raise PuzzleNotFound()
    if record.progress != "in_progress":
        raise PuzzleAlreadyDone()

    snapshot = record.snapshot or {}
    answer: dict[str, str | None] = snapshot.get("answer", {})
    node_ids = set(answer.keys())
    if set(assignments.keys()) != node_ids:
        raise ValueError("拼装结果必须覆盖全部节点")

    correct = 0
    details: dict[str, bool] = {}
    for nid, expected in answer.items():
        given = assignments.get(nid)
        given = str(given) if given else None
        is_ok = given == expected
        details[nid] = is_ok
        correct += 1 if is_ok else 0

    record.result = {"correct": correct, "total": len(answer), "details": details}
    record.progress = "done"
    record.completed_at = _now()
    await db.commit()
    return {
        "puzzle_id": str(record.id),
        "correct": correct,
        "total": len(answer),
        "details": details,
        "completed_at": str(record.completed_at),
    }
