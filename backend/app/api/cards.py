"""知识卡片路由（tasks.md 5.3，design.md §2.2.2.3）。"""
import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.infrastructure import redis_client, task_runner
from app.logging_config import log_action
from app.models import User
from app.schemas.response import ERR_VALIDATION, fail, ok
from app.services import card_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cards", tags=["cards"])


def _card_payload(card) -> dict:
    return {
        "id": str(card.id),
        "kb_id": str(card.kb_id),
        "asset_id": str(card.asset_id),
        "title": card.title,
        "summary": card.summary,
        "key_points": card.key_points,
        "qa_pairs": card.qa_pairs,
        "tags": card.tags or [],
        "review_interval_days": card.review_interval_days,
        "review_count": card.review_count,
        "created_at": str(card.created_at),
    }


class CardUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    summary: str | None = Field(default=None, max_length=300)
    key_points: list[str] | None = None
    qa_pairs: list[dict] | None = None
    tags: list[str] | None = None


class MoveRequest(BaseModel):
    target_kb_id: str


@router.get("", response_model=dict)
async def list_cards(
    kb_id: str | None = None,
    tag: str | None = None,
    page: int = 1,
    size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """卡片列表（分页、kb/tag筛选，spec §5.3）。

    按库分页查询走 Redis card_list:{kb_id}:{page} 缓存 TTL 3min（design §2.5.3、tasks.md 6.2），
    写操作后由各 service delete 失效；tag 筛选与跨库查询不缓存。
    """
    page = max(page, 1)
    size = min(max(size, 1), 100)

    cache_key = None
    if kb_id and not tag:
        cache_key = redis_client.KEY_CARD_LIST.format(kb_id=kb_id, page=page)
        cached = await redis_client.cache_get(cache_key)
        if cached:
            data = json.loads(cached)
            data["page"], data["size"] = page, size
            return ok(data=data)

    cards, total = await card_service.list_cards(db, user.id, kb_id, tag, page, size)
    data = {"items": [_card_payload(c) for c in cards], "total": total, "page": page, "size": size}
    if cache_key:
        await redis_client.cache_set(cache_key, json.dumps(data, ensure_ascii=False), ttl=180)
    return ok(data=data)


@router.get("/{card_id}", response_model=dict)
async def get_card(
    card_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """卡片详情（spec §5.3.1规则2 溯源）。"""
    card = await card_service.get_card(db, card_id, user.id)
    if card is None:
        return fail(40400, "卡片不存在", status_code=404)
    return ok(data=_card_payload(card))


@router.put("/{card_id}", response_model=dict)
async def update_card(
    card_id: str,
    payload: CardUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """编辑卡片（标题/要点/问答/标签，spec §5.3.1规则3）。"""
    card = await card_service.get_card(db, card_id, user.id)
    if card is None:
        return fail(40400, "卡片不存在", status_code=404)
    try:
        card = await card_service.update_card(db, card, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    log_action(logger, "card:update", user_id=user.id, card_id=card_id)
    return ok(data=_card_payload(card))


@router.delete("/{card_id}", response_model=dict)
async def delete_card(
    card_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除卡片（级联清理复习任务与导图引用，spec §5.3.1规则4）。"""
    card = await card_service.get_card(db, card_id, user.id)
    if card is None:
        return fail(40400, "卡片不存在", status_code=404)
    await card_service.delete_card(db, card)
    log_action(logger, "card:delete", user_id=user.id, card_id=card_id)
    return ok(message="卡片已删除")


@router.post("/{card_id}/move", response_model=dict)
async def move_card(
    card_id: str,
    payload: MoveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """移动卡片至其他知识库（spec §5.4.1规则2）。"""
    card = await card_service.get_card(db, card_id, user.id)
    if card is None:
        return fail(40400, "卡片不存在", status_code=404)
    from app.models import KnowledgeBase
    from sqlalchemy import select

    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == payload.target_kb_id, KnowledgeBase.user_id == user.id
        )
    )
    if kb_result.scalar_one_or_none() is None:
        return fail(40400, "目标知识库不存在", status_code=404)
    await card_service.move_card(db, card, payload.target_kb_id)
    log_action(logger, "card:move", user_id=user.id, card_id=card_id, target=payload.target_kb_id)
    return ok(message="移动成功")
