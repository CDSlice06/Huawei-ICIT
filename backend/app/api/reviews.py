"""复习路由（tasks.md 8.2/8.3，design.md §2.2.2.6）。"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.logging_config import log_action
from app.models import User
from app.schemas.response import ERR_CONFLICT, ERR_VALIDATION, fail, ok
from app.services import review_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reviews", tags=["reviews"])


class RatingRequest(BaseModel):
    rating: str  # forget | blur | remember


@router.get("/today", response_model=dict)
async def today_tasks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """今日待复习清单（spec §5.6.1规则3）。"""
    items = await review_service.list_today_tasks(db, user.id)
    return ok(data={"items": items, "total": len(items)})


@router.post("/{task_id}/submit", response_model=dict)
async def submit_rating(
    task_id: str,
    payload: RatingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """提交掌握度自评（spec §5.6.1规则2）。"""
    try:
        result = await review_service.submit_rating(db, user.id, task_id, payload.rating)
    except review_service.InvalidRating:
        return fail(ERR_VALIDATION, "自评值非法（forget/blur/remember）", status_code=422)
    except review_service.TaskNotFound:
        return fail(40400, "复习任务不存在", status_code=404)
    except review_service.TaskAlreadyDone:
        return fail(ERR_CONFLICT, "该任务已完成，请勿重复提交", status_code=409)
    log_action(logger, "review:submit", user_id=user.id, task_id=task_id, rating=payload.rating)
    return ok(data=result)