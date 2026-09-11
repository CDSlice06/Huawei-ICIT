"""知识素材路由（tasks.md 4.1，design.md §2.2.2.2）。"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.infrastructure import task_runner
from app.logging_config import log_action
from app.models import User
from app.schemas.response import ERR_RATE_LIMIT, ERR_VALIDATION, fail, ok
from app.services import import_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])


class TextImportRequest(BaseModel):
    content: str = Field(description="文本内容，≤5000字符")
    kb_id: str | None = Field(default=None, description="目标知识库，缺省写入默认知识库")


@router.post("/text", status_code=202, response_model=dict)
async def import_text(
    payload: TextImportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """文本导入（P0）：一键零配置，创建素材+异步结构化任务（spec §5.2.1规则1/6）。"""
    if len(payload.content) > settings.TEXT_MAX_CHARS:
        return fail(
            ERR_VALIDATION,
            f"文本超出{settings.TEXT_MAX_CHARS}字符上限（当前{len(payload.content)}字符）",
            status_code=422,
        )
    try:
        await import_service.check_concurrency_gate(db, user.id)
    except import_service.GateLimitReached:
        return fail(ERR_RATE_LIMIT, "已有任务解析中，请稍候", status_code=429)

    try:
        asset, task = await import_service.create_text_asset(
            db, user.id, payload.content, payload.kb_id
        )
    except import_service.KnowledgeBaseNotFound:
        return fail(ERR_VALIDATION, "目标知识库不存在", status_code=422)

    task_runner.submit_task(str(task.id))
    log_action(logger, "asset:text_import", user_id=user.id, asset_id=asset.id)
    return ok(data={"task_id": str(task.id), "asset_id": str(asset.id)}, message="解析中")


@router.get("/{asset_id}", response_model=dict)
async def get_asset(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """素材详情：原始内容/提取文本/解析状态（spec §5.2.1规则4）。"""
    try:
        asset = await import_service.get_owned_asset(db, asset_id, user.id)
    except import_service.AssetNotFound:
        return fail(40400, "素材不存在", status_code=404)
    return ok(data={
        "id": str(asset.id),
        "type": asset.type,
        "kb_id": str(asset.kb_id) if asset.kb_id else None,
        "raw_content": asset.raw_content,
        "obs_key": asset.obs_key,
        "extracted_text": asset.extracted_text,
        "parse_status": asset.parse_status,
        "created_at": str(asset.created_at),
    })


@router.delete("/{asset_id}", response_model=dict)
async def delete_asset(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除素材。"""
    try:
        await import_service.delete_asset(db, asset_id, user.id)
    except import_service.AssetNotFound:
        return fail(40400, "素材不存在", status_code=404)
    log_action(logger, "asset:delete", user_id=user.id, asset_id=asset_id)
    return ok(message="素材已删除")


@router.post("/{asset_id}/restruct", response_model=dict, status_code=202)
async def restruct(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重新生成卡片（覆盖前二次确认由前端承担，spec §5.3.3异常3）。"""
    from app.services import card_service

    try:
        task = await card_service.restruct_asset(db, asset_id, user.id)
    except ValueError:
        return fail(40400, "素材不存在", status_code=404)
    from app.infrastructure import task_runner

    task_runner.submit_task(str(task.id))
    log_action(logger, "asset:restruct", user_id=user.id, asset_id=asset_id)
    return ok(data={"task_id": str(task.id)}, message="解析中")