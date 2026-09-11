"""搜索与标签路由（P1-4/P1-5，spec §5.4.1规则4/6）。

- GET /api/search：卡片/素材/错题三类全局与库内搜索（MySQL FTS ngram，兼容层LIKE降级）
- GET /api/tags：用户卡片标签聚合，供按标签浏览
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.logging_config import log_action
from app.models import User
from app.schemas.response import ERR_VALIDATION, fail, ok
from app.services import search_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["search"])


@router.get("/search", response_model=dict)
async def search(
    keyword: str = Query(description="搜索关键词"),
    kb_id: str | None = Query(default=None, description="库内搜索范围"),
    type: str = Query(default="all", description="all / card / asset / mistake"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """全局/库内知识搜索（三类对象、相关性排序，spec §4.1.4 ≤2s）。"""
    try:
        data = await search_service.search_all(db, user.id, keyword, kb_id, type)
    except search_service.SearchValidationError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    log_action(logger, "search", user_id=user.id, keyword=keyword[:50],
               hits=sum(data["counts"].values()))
    return ok(data=data)


@router.get("/tags", response_model=dict)
async def list_tags(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户卡片标签聚合（按使用次数排序）。"""
    tags = await search_service.aggregate_tags(db, user.id)
    return ok(data={"items": tags, "total": len(tags)})
