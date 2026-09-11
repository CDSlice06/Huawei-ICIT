"""导图拼图自测路由（P2-2，spec §5.5.1规则8~10、§6.11）。"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.logging_config import log_action
from app.models import User
from app.schemas.response import ERR_CONFLICT, ERR_VALIDATION, fail, ok
from app.services import puzzle_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/map-puzzles", tags=["map-puzzles"])


class PuzzleCreateRequest(BaseModel):
    kb_id: str


class PuzzleSubmitRequest(BaseModel):
    assignments: dict[str, str | None] = Field(description="{node_id: 父节点id或null(根)}")


@router.post("", status_code=201, response_model=dict)
async def create_puzzle(
    payload: PuzzleCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发起拼图自测：打散快照（逐层拼装模式，spec §5.5.1规则8）。"""
    try:
        data = await puzzle_service.create_puzzle(db, user.id, payload.kb_id)
    except puzzle_service.PuzzleKbNotFound:
        return fail(40400, "知识库不存在", status_code=404)
    except puzzle_service.PuzzleMapMissing:
        return fail(40400, "该库还没有思维导图，请先生成", status_code=404)
    except puzzle_service.PuzzleTooSmall:
        return fail(ERR_VALIDATION, "导图节点过少（至少2个），无法拼图", status_code=422)
    log_action(logger, "puzzle:start", user_id=user.id, kb_id=payload.kb_id)
    return ok(data=data, message="拼图已开始")


@router.get("/{puzzle_id}", response_model=dict)
async def get_puzzle(
    puzzle_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """作答视图（不含答案键）或已完成的结果。"""
    data = await puzzle_service.get_puzzle(db, puzzle_id, user.id)
    if data is None:
        return fail(40400, "拼图记录不存在", status_code=404)
    return ok(data=data)


@router.post("/{puzzle_id}/submit", response_model=dict)
async def submit_puzzle(
    puzzle_id: str,
    payload: PuzzleSubmitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """提交拼装结果：按父子关系一致性判定（spec §6.11规则5）。"""
    try:
        data = await puzzle_service.submit_puzzle(db, puzzle_id, user.id, payload.assignments)
    except ValueError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    except puzzle_service.PuzzleNotFound:
        return fail(40400, "拼图记录不存在", status_code=404)
    except puzzle_service.PuzzleAlreadyDone:
        return fail(ERR_CONFLICT, "该拼图已完成", status_code=409)
    log_action(logger, "puzzle:submit", user_id=user.id, puzzle_id=puzzle_id,
               correct=data["correct"], total=data["total"])
    return ok(data=data, message="拼装判定完成")
