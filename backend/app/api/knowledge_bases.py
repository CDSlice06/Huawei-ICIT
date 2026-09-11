"""知识库路由（tasks.md 6.1，design.md §2.2.2.4）。"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.logging_config import log_action
from app.models import User
from app.schemas.response import ERR_CONFLICT, ERR_VALIDATION, fail, ok
from app.services import kb_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


class KbCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)


@router.post("", response_model=dict)
async def create_kb(
    payload: KbCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建知识库（spec §5.4.1规则1）。"""
    try:
        kb = await kb_service.create_kb(db, user.id, payload.name.strip())
    except kb_service.KbNameConflict:
        return fail(ERR_CONFLICT, "同名知识库已存在", status_code=409)
    except ValueError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    log_action(logger, "kb:create", user_id=user.id, kb_id=kb.id)
    return ok(data={"id": str(kb.id), "name": kb.name}, message="创建成功")


@router.get("", response_model=dict)
async def list_kbs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """知识库列表（Redis缓存，spec §5.4.2）。"""
    items = await kb_service.list_kbs(db, user.id)
    return ok(data=items)


@router.put("/{kb_id}", response_model=dict)
async def rename_kb(
    kb_id: str,
    payload: KbCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重命名知识库（spec §5.4.1规则1）。"""
    try:
        kb = await kb_service.rename_kb(db, user.id, kb_id, payload.name.strip())
    except kb_service.KbNotFound:
        return fail(40400, "知识库不存在", status_code=404)
    except kb_service.KbNameConflict:
        return fail(ERR_CONFLICT, "同名知识库已存在", status_code=409)
    except ValueError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    log_action(logger, "kb:rename", user_id=user.id, kb_id=kb_id)
    return ok(data={"id": str(kb.id), "name": kb.name})


@router.delete("/{kb_id}", response_model=dict)
async def delete_kb(
    kb_id: str,
    confirm: bool = False,
    share_action: str = "keep",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除知识库。

    confirm=false 时仅返回级联删除规模（供前端确认弹窗明示数量）；
    confirm=true 时执行级联删除（spec §5.4.1规则3、§5.4.3异常1）。
    """
    try:
        kb = await kb_service.get_owned_kb(db, user.id, kb_id)
    except kb_service.KbNotFound:
        return fail(40400, "知识库不存在", status_code=404)
    if not confirm:
        card_count = await kb_service.count_cards(db, kb_id)
        has_shared = await kb_service.count_active_shares(db, kb_id) > 0
        return ok(data={"require_confirm": True, "card_count": card_count, "has_shared": has_shared})
    try:
        deleted = await kb_service.delete_kb(db, user.id, kb_id, share_action=share_action)
    except kb_service.KbNotFound:
        return fail(40400, "知识库不存在", status_code=404)
    log_action(logger, "kb:delete", user_id=user.id, kb_id=kb_id, deleted_cards=deleted)
    return ok(data={"deleted_cards": deleted}, message="知识库已删除")