"""知识分享论坛路由（P2-1，spec §5.7、design §2.2.2.7）。

论坛向全体登录用户开放（只读）；发布/更新/取消仅限分享者本人；
无评论/点赞/关注/私信等任何社交互动（spec §5.7.1规则8 禁止项）。
"""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.dependencies import get_current_user
from app.logging_config import log_action
from app.models import User
from app.schemas.response import ERR_CONFLICT, ERR_VALIDATION, fail, ok
from app.services import forum_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/forum", tags=["forum"])


class ShareRequest(BaseModel):
    kb_id: str
    title: str | None = Field(default=None, max_length=50, description="快照标题，缺省用库名")


@router.post("/shares", status_code=201, response_model=dict)
async def create_share(
    payload: ShareRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分享知识库（生成发布快照，spec §5.7.1规则1）。"""
    try:
        record = await forum_service.share_kb(db, user.id, payload.kb_id, payload.title)
    except forum_service.KbNotFound:
        return fail(40400, "知识库不存在", status_code=404)
    except forum_service.ShareConflict:
        return fail(ERR_CONFLICT, "该知识库已分享至论坛", status_code=409)
    except forum_service.KbHasNoCards:
        return fail(ERR_VALIDATION, "空知识库无法分享，请先导入知识卡片", status_code=422)
    log_action(logger, "forum:share", user_id=user.id, share_id=record.id)
    return ok(data={"id": str(record.id), "title": record.snapshot_title}, message="分享成功")


@router.get("/shares", response_model=dict)
async def list_shares(
    mine: bool = Query(default=False, description="true=我的分享（含已取消）"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """论坛列表（全体可见）或我的分享管理列表。"""
    if mine:
        items = await forum_service.list_mine(db, user.id)
    else:
        items = await forum_service.list_shares(db)
    return ok(data={"items": items, "total": len(items)})


@router.get("/shares/{share_id}", response_model=dict)
async def get_share(
    share_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """只读浏览分享快照（spec §5.7.1规则5~6；已取消即下线）。"""
    data = await forum_service.get_share_detail(db, share_id)
    if data is None:
        return fail(40400, "该分享不存在或已取消", status_code=404)
    return ok(data=data)


@router.put("/shares/{share_id}", response_model=dict)
async def update_share(
    share_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """更新分享：以原库当前内容重新生成快照覆盖（spec §5.7.1规则3，二次确认由前端承担）。"""
    try:
        share = await forum_service.update_share(db, share_id, user.id)
    except forum_service.ShareNotFound:
        return fail(40400, "分享不存在或已取消", status_code=404)
    log_action(logger, "forum:update_share", user_id=user.id, share_id=share_id)
    return ok(data={"id": share_id, "updated_at": str(share.updated_at)}, message="快照已更新")



@router.delete("/shares/{share_id}", response_model=dict)
async def cancel_share(
    share_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """取消分享：论坛即时下线，原库数据不受影响（spec §5.7.1规则4）。"""
    try:
        await forum_service.cancel_share(db, share_id, user.id)
    except forum_service.ShareNotFound:
        return fail(40400, "分享不存在或已取消", status_code=404)
    log_action(logger, "forum:cancel_share", user_id=user.id, share_id=share_id)
    return ok(message="分享已取消")
