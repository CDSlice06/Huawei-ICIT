"""错题本路由（P1-1，spec §5.8、design §2.2.2.8）。

录入走 mistake_parse 异步任务链（MaaS调用不阻塞，202返回）；
测验遵循"仅题目→揭示答案→标记"交互，条目掌握状态即时更新。
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.infrastructure import task_runner
from app.logging_config import log_action
from app.models import MistakeEntry, User
from app.schemas.response import ERR_CONFLICT, ERR_RATE_LIMIT, ERR_VALIDATION, fail, ok
from app.services import import_service, mistake_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mistakes", tags=["mistakes"])


def _mistake_payload(entry: MistakeEntry) -> dict:
    return {
        "id": str(entry.id),
        "question": entry.question,
        "answer": entry.answer,
        "error_analysis": entry.error_analysis,
        "tags": entry.tags or [],
        "source_type": entry.source_type,
        "obs_key": entry.obs_key,
        "kb_id": str(entry.kb_id) if entry.kb_id else None,
        "card_id": str(entry.card_id) if entry.card_id else None,
        "mastery": entry.mastery,
        "parse_status": entry.parse_status,
        "created_at": str(entry.created_at),
    }


class TextMistakeRequest(BaseModel):
    content: str = Field(description="错题文本描述，≤5000字符")


class ImageMistakeRequest(BaseModel):
    obs_key: str = Field(description="原图OBS对象键（P1-3直传后回传）", max_length=512)


class MistakeUpdateRequest(BaseModel):
    question: str | None = Field(default=None, max_length=2000)
    answer: str | None = Field(default=None, max_length=2000)
    error_analysis: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = None
    kb_id: str | None = None
    card_id: str | None = None


class MasteryRequest(BaseModel):
    mastery: str = Field(description="unmastered / mastered")


class QuizStartRequest(BaseModel):
    strategy: str = Field(description="sequential(按顺序) / random(随机)")
    count: int = Field(default=10, description="抽取数量")
    scope: str = Field(default="unmastered", description="unmastered(默认) / all")


class QuizAnswerRequest(BaseModel):
    entry_id: str
    mark: str = Field(description="mastered(已掌握) / still_not(仍不会)")


class QuizStatusRequest(BaseModel):
    status: str = Field(description="abandoned(放弃)")


async def _gate(db: AsyncSession, user: User) -> dict | None:
    """单用户并发解析闸门（mistake_parse 与 structure/map_gen 合并计数，design §2.1.3.1）。"""
    try:
        await import_service.check_concurrency_gate(db, user.id)
    except import_service.GateLimitReached:
        return fail(ERR_RATE_LIMIT, "已有任务解析中，请稍候", status_code=429)
    return None


@router.post("/text", status_code=202, response_model=dict)
async def create_text_mistake(
    payload: TextMistakeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """文本录入错题：一键解析（异步任务链，spec §5.8.1规则1）。"""
    if len(payload.content) > settings.TEXT_MAX_CHARS:
        return fail(
            ERR_VALIDATION,
            f"文本超出{settings.TEXT_MAX_CHARS}字符上限（当前{len(payload.content)}字符）",
            status_code=422,
        )
    if blocked := await _gate(db, user):
        return blocked
    entry, task = await mistake_service.create_text_mistake(db, user.id, payload.content)
    task_runner.submit_task(str(task.id))
    log_action(logger, "mistake:text_import", user_id=user.id, mistake_id=entry.id)
    return ok(data={"task_id": str(task.id), "mistake_id": str(entry.id)}, message="解析中")


@router.post("/image", status_code=202, response_model=dict)
async def create_image_mistake(
    payload: ImageMistakeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """图片录入错题：MaaS多模态一次调用（OCR+解析，120s超时）。"""
    if blocked := await _gate(db, user):
        return blocked
    entry, task = await mistake_service.create_image_mistake(db, user.id, payload.obs_key)
    task_runner.submit_task(str(task.id))
    log_action(logger, "mistake:image_import", user_id=user.id, mistake_id=entry.id)
    return ok(data={"task_id": str(task.id), "mistake_id": str(entry.id)}, message="识别解析中")


@router.get("", response_model=dict)
async def list_mistakes(
    mastery: str = "all",
    parse_status: str | None = None,
    page: int = 1,
    size: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """错题本列表（mastery/parse_status筛选、分页，created_at倒序）。"""
    page = max(page, 1)
    size = min(max(size, 1), 100)
    items, total = await mistake_service.list_mistakes(db, user.id, mastery, parse_status, page, size)
    return ok(data={"items": [_mistake_payload(e) for e in items], "total": total, "page": page, "size": size})


@router.post("/quiz", status_code=201, response_model=dict)
async def start_quiz(
    payload: QuizStartRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发起测验：按策略抽取条目，返回"仅题目"序列（答案揭示前不可见）。"""
    try:
        record, picked = await mistake_service.start_quiz(db, user.id, payload.strategy, payload.count, payload.scope)
    except ValueError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    except mistake_service.EmptyQuizRange:
        return fail(
            ERR_VALIDATION,
            "所选范围内暂无可用错题，请调整抽取范围或先录入错题",
            status_code=422,
        )
    log_action(logger, "mistake:quiz_start", user_id=user.id, quiz_id=record.id, count=len(picked))
    return ok(
        data={
            "quiz_id": str(record.id),
            "strategy": record.strategy,
            "scope": record.scope,
            "total": len(picked),
            "items": [mistake_service.entry_public(e) for e in picked],
        },
        message="测验已开始",
    )


@router.get("/quiz/{quiz_id}", response_model=dict)
async def get_quiz(
    quiz_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """测验进度（中断恢复：已答标记+未答题目序列）。"""
    data = await mistake_service.get_quiz(db, quiz_id, user.id)
    if data is None:
        return fail(40400, "测验记录不存在", status_code=404)
    return ok(data=data)


@router.post("/quiz/{quiz_id}/answer", response_model=dict)
async def submit_quiz_answer(
    quiz_id: str,
    payload: QuizAnswerRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """提交单题标记：即时更新条目掌握状态（spec §5.8.1规则6）。"""
    try:
        result = await mistake_service.submit_answer(db, quiz_id, user.id, payload.entry_id, payload.mark)
    except ValueError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    except mistake_service.QuizNotFound:
        return fail(40400, "测验记录不存在", status_code=404)
    except mistake_service.QuizAlreadyFinished:
        return fail(ERR_CONFLICT, "测验已结束", status_code=409)
    except mistake_service.EntryNotInQuiz:
        return fail(40400, "条目不在本次测验内或已标记", status_code=404)
    return ok(data=result)


@router.patch("/quiz/{quiz_id}/status", response_model=dict)
async def update_quiz_status(
    quiz_id: str,
    payload: QuizStatusRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """放弃测验（已提交的掌握状态更新不回滚，spec §5.8.3异常4）。"""
    if payload.status != "abandoned":
        return fail(ERR_VALIDATION, "status 仅支持 abandoned", status_code=422)
    try:
        await mistake_service.abandon_quiz(db, quiz_id, user.id)
    except mistake_service.QuizNotFound:
        return fail(40400, "测验记录不存在", status_code=404)
    except mistake_service.QuizAlreadyFinished:
        return fail(ERR_CONFLICT, "测验已结束", status_code=409)
    log_action(logger, "mistake:quiz_abandon", user_id=user.id, quiz_id=quiz_id)
    return ok(message="测验已放弃")


@router.get("/{entry_id}", response_model=dict)
async def get_mistake(
    entry_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """条目详情（测验"揭示答案"亦经此接口取答案与解析；他人资源404）。"""
    entry = await mistake_service.get_mistake(db, entry_id, user.id)
    if entry is None:
        return fail(40400, "错题条目不存在", status_code=404)
    return ok(data=_mistake_payload(entry))


@router.put("/{entry_id}", response_model=dict)
async def update_mistake(
    entry_id: str,
    payload: MistakeUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """编辑条目任一字段（spec §5.8.1规则3）。"""
    entry = await mistake_service.get_mistake(db, entry_id, user.id)
    if entry is None:
        return fail(40400, "错题条目不存在", status_code=404)
    fields = payload.model_dump(exclude_unset=True)
    # 关联知识库/卡片必须为本人名下（§6.9规则9）
    for key in ("kb_id", "card_id"):
        target_id = fields.get(key)
        if target_id:
            from sqlalchemy import select

            from app.models import KnowledgeCard, KnowledgeBase

            model = KnowledgeBase if key == "kb_id" else KnowledgeCard
            row = (
                await db.execute(select(model).where(model.id == target_id, model.user_id == user.id))
            ).scalar_one_or_none()
            if row is None:
                return fail(40400, f"关联{'知识库' if key == 'kb_id' else '卡片'}不存在", status_code=404)
    try:
        await mistake_service.update_mistake(db, entry, fields)
    except ValueError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    log_action(logger, "mistake:update", user_id=user.id, mistake_id=entry_id)
    return ok(data=_mistake_payload(entry))


@router.delete("/{entry_id}", response_model=dict)
async def delete_mistake(
    entry_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """删除条目（二次确认由前端承担）。"""
    entry = await mistake_service.get_mistake(db, entry_id, user.id)
    if entry is None:
        return fail(40400, "错题条目不存在", status_code=404)
    await mistake_service.delete_mistake(db, entry)
    log_action(logger, "mistake:delete", user_id=user.id, mistake_id=entry_id)
    return ok(message="错题已删除")


@router.patch("/{entry_id}/mastery", response_model=dict)
async def set_mastery(
    entry_id: str,
    payload: MasteryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手动更新掌握状态（已掌握可重置回未掌握，spec §5.8.1规则7b）。"""
    entry = await mistake_service.get_mistake(db, entry_id, user.id)
    if entry is None:
        return fail(40400, "错题条目不存在", status_code=404)
    try:
        await mistake_service.set_mastery(db, entry, payload.mastery)
    except ValueError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    return ok(data=_mistake_payload(entry))


@router.post("/{entry_id}/reparse", status_code=202, response_model=dict)
async def reparse_mistake(
    entry_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """重新解析（解析失败重试/覆盖确认由前端承担，spec §5.8.3异常2）。"""
    entry = await mistake_service.get_mistake(db, entry_id, user.id)
    if entry is None:
        return fail(40400, "错题条目不存在", status_code=404)
    if blocked := await _gate(db, user):
        return blocked
    task = await mistake_service.reparse_mistake(db, entry)
    task_runner.submit_task(str(task.id))
    log_action(logger, "mistake:reparse", user_id=user.id, mistake_id=entry_id)
    return ok(data={"task_id": str(task.id), "mistake_id": str(entry.id)}, message="解析中")
