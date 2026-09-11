"""思维导图路由（tasks.md 7.1/7.2，design.md §2.2.2.5）。"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import NotFoundError, get_current_user
from app.infrastructure import task_runner
from app.logging_config import log_action
from app.models import User
from app.schemas.response import ERR_RATE_LIMIT, fail, ok
from app.services import import_service, kb_service, map_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mind-maps", tags=["mind-maps"])


class MapGenRequest(BaseModel):
    kb_id: str


@router.post("/generate", response_model=dict, status_code=202)
async def generate_map(
    payload: MapGenRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """一键生成导图（异步，type=map_gen，spec §5.5.1规则1）。

    MaaS层级提炼耗时30s+，走异步任务链（tasks.md 决策记录4），
    前端复用任务状态流（SSE/轮询）等待完成。
    """
    try:
        await kb_service.get_owned_kb(db, user.id, payload.kb_id)
    except kb_service.KbNotFound:
        return fail(40400, "知识库不存在", status_code=404)
    # 单用户并发闸门同样约束map_gen（design §2.1.3.1 单用户并发解析闸门≤2）
    try:
        await import_service.check_concurrency_gate(db, user.id)
    except import_service.GateLimitReached:
        return fail(ERR_RATE_LIMIT, "已有任务解析中，请稍候", status_code=429)
    task = await map_service.create_map_gen_task(db, user.id, payload.kb_id)
    task_runner.submit_task(str(task.id))
    log_action(logger, "map:generate", user_id=user.id, kb_id=payload.kb_id)
    return ok(data={"task_id": str(task.id)}, message="导图生成中")


@router.get("/{kb_id}", response_model=dict)
async def get_map(
    kb_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """获取导图（节点树+坐标+版本来源，spec §5.5.1规则2~3）。他人知识库统一404。"""
    try:
        await kb_service.get_owned_kb(db, user.id, kb_id)
    except kb_service.KbNotFound:
        raise NotFoundError()
    data = await map_service.get_map_by_kb(db, user.id, kb_id)
    if data is None:
        return ok(data=None, message="暂无导图")
    return ok(data=data)