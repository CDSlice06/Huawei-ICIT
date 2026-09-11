"""错题本服务（P1-1，spec §5.8/§6.9~§6.10、design §2.1.3.5/§2.2.2.8）。

- 错题录入：文本/图片（MaaS多模态一次调用OCR+解析）走 mistake_parse 异步任务链
- 解析失败不落残缺条目：条目保留原文（raw_content），parse_status=failed 支持重试（§5.8.3异常2）
- 测验：仅从用户本人错题本抽取（禁止AI出题，§5.8.1规则4），顺序/随机策略，
  先题目后揭示、逐题标记即时更新掌握状态（规则6）、中断恢复（§5.8.3异常4）
"""
import logging
import random
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.maas_client import MaasError, get_maas_client
from app.infrastructure.prompts import (
    MISTAKE_IMAGE_USER_PROMPT,
    MISTAKE_SYSTEM_PROMPT,
    MISTAKE_USER_TEMPLATE,
)
from app.models import AsyncTask, MistakeEntry, MistakeQuizRecord

logger = logging.getLogger(__name__)

QUIZ_MAX_COUNT = 50  # 单次测验题目数上限（§5.8.1规则5"限定抽取数量"的合理上界）


class MistakeSchemaError(Exception):
    """错题解析输出校验失败（不落残缺条目，spec §5.8.3异常2）。"""


class MistakeNotFound(Exception):
    """错题条目不存在或无权访问。"""


class QuizNotFound(Exception):
    """测验记录不存在或无权访问。"""


class QuizAlreadyFinished(Exception):
    """测验已结束（完成/放弃），不能再作答或重复放弃。"""


class EntryNotInQuiz(Exception):
    """提交的条目不在本次测验序列内，或已标记过。"""


class EmptyQuizRange(Exception):
    """抽取范围内无可用条目（spec §5.8.3异常3）。"""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _validate_mistake_schema(data: dict) -> dict:
    """校验错题解析输出（spec §6.9约束、§5.8.3异常2：关键字段缺失不落库）。

    题目内容/正确答案/错误原因解析必填非空≤2000字符；标签可选，合计≤10个每个≤20字符。
    """
    errors: list[str] = []
    question = (data.get("question") or "").strip()
    answer = (data.get("answer") or "").strip()
    error_analysis = (data.get("error_analysis") or "").strip()
    tags = data.get("tags") or []

    if not question:
        errors.append("题目内容缺失")
    elif len(question) > 2000:
        errors.append("题目内容超过2000字符")
    if not answer:
        errors.append("正确答案缺失")
    elif len(answer) > 2000:
        errors.append("正确答案超过2000字符")
    if not error_analysis:
        errors.append("错误原因解析缺失")
    elif len(error_analysis) > 2000:
        errors.append("错误原因解析超过2000字符")
    if not isinstance(tags, list) or len(tags) > 10:
        errors.append("标签须为数组且不超过10个")
    elif any(not isinstance(t, str) or not t.strip() or len(t) > 20 for t in tags):
        errors.append("标签为空或超过20字符")

    if errors:
        raise MistakeSchemaError("；".join(errors))
    return {
        "question": question,
        "answer": answer,
        "error_analysis": error_analysis,
        "tags": [t.strip() for t in tags],
    }


def _multimodal_image_url(obs_key: str) -> str:
    """由 OBS 配置拼装图片可访问 URL（P1-3 直传链路的前置约定）。"""
    from app.config import settings

    if not settings.OBS_ENDPOINT:
        raise MaasError("图片录入依赖OBS对象存储（OBS_ENDPOINT未配置），请先完成华为云OBS配置或改用文本录入")
    return f"{settings.OBS_ENDPOINT.rstrip('/')}/{obs_key.lstrip('/')}"


async def mistake_parse_task_handler(db: AsyncSession, task: AsyncTask) -> dict:
    """mistake_parse 任务 handler（任务链复用4.2 TaskRunner）。

    文本：raw_content → MaaS解析；图片：OBS图URL → MaaS多模态一次调用（OCR+解析，120s超时）。
    每次尝试开始置 parsing，失败置 failed 并抛出走重试（素材/原文保留，spec §5.8.3异常1~2）。
    """
    entry_result = await db.execute(select(MistakeEntry).where(MistakeEntry.id == task.ref_id))
    entry = entry_result.scalar_one_or_none()
    if entry is None or entry.user_id != task.user_id:
        raise MistakeNotFound(f"错题条目 {task.ref_id} 不存在")

    entry.parse_status = "parsing"
    await db.commit()

    client = get_maas_client()
    try:
        if entry.source_type == "image":
            raw = await client.chat_json(
                [
                    {"role": "system", "content": MISTAKE_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": MISTAKE_IMAGE_USER_PROMPT},
                            {"type": "image_url", "image_url": {"url": _multimodal_image_url(entry.obs_key or "")}},
                        ],
                    },
                ],
                multimodal=True,  # 图片识别120s超时（spec §4.1.2）
            )
            # OCR 无法识别时模型按约定返回空 question → 校验失败走解析失败分支（§5.8.3异常1）
            data = _validate_mistake_schema(raw)
        else:
            raw = await client.chat_json(
                [
                    {"role": "system", "content": MISTAKE_SYSTEM_PROMPT},
                    {"role": "user", "content": MISTAKE_USER_TEMPLATE.format(content=entry.raw_content or "")},
                ]
            )
            data = _validate_mistake_schema(raw)
    except Exception:
        entry.parse_status = "failed"
        await db.commit()
        raise

    entry.question = data["question"]
    entry.answer = data["answer"]
    entry.error_analysis = data["error_analysis"]
    entry.tags = data["tags"]
    entry.parse_status = "done"
    await db.commit()
    logger.info("mistake:parse_done", extra={"user_id": task.user_id, "mistake_id": str(entry.id)})
    return {"mistake_id": str(entry.id), "question": entry.question[:50]}


async def create_text_mistake(db: AsyncSession, user_id: str, content: str) -> tuple[MistakeEntry, AsyncTask]:
    """文本录入：条目先于任务落盘保留原文（§4.2.3数据不丢失），返回202要素。"""
    entry = MistakeEntry(
        user_id=user_id,
        source_type="text",
        raw_content=content,
        parse_status="parsing",
        created_at=_now(),
    )
    db.add(entry)
    await db.flush()
    task = AsyncTask(
        user_id=user_id, type="mistake_parse", ref_id=entry.id, status="pending", created_at=_now()
    )
    db.add(task)
    await db.commit()
    return entry, task


async def create_image_mistake(db: AsyncSession, user_id: str, obs_key: str) -> tuple[MistakeEntry, AsyncTask]:
    """图片录入：原图引用入条目（溯源查看，§6.9规则8），OCR+解析走多模态任务。"""
    entry = MistakeEntry(
        user_id=user_id,
        source_type="image",
        obs_key=obs_key,
        parse_status="parsing",
        created_at=_now(),
    )
    db.add(entry)
    await db.flush()
    task = AsyncTask(
        user_id=user_id, type="mistake_parse", ref_id=entry.id, status="pending", created_at=_now()
    )
    db.add(task)
    await db.commit()
    return entry, task


async def reparse_mistake(db: AsyncSession, entry: MistakeEntry) -> AsyncTask:
    """重新解析（解析失败重试/覆盖前确认由前端承担，§5.8.3异常2）。"""
    entry.parse_status = "parsing"
    task = AsyncTask(
        user_id=entry.user_id, type="mistake_parse", ref_id=entry.id, status="pending", created_at=_now()
    )
    db.add(task)
    await db.commit()
    return task


async def list_mistakes(
    db: AsyncSession, user_id: str, mastery: str | None, parse_status: str | None, page: int, size: int
) -> tuple[list[MistakeEntry], int]:
    """错题本列表（mastery/解析状态筛选，created_at倒序）。"""
    from sqlalchemy import func

    query = select(MistakeEntry).where(MistakeEntry.user_id == user_id)
    count_query = select(func.count()).select_from(MistakeEntry).where(MistakeEntry.user_id == user_id)
    if mastery and mastery != "all":
        query = query.where(MistakeEntry.mastery == mastery)
        count_query = count_query.where(MistakeEntry.mastery == mastery)
    if parse_status:
        query = query.where(MistakeEntry.parse_status == parse_status)
        count_query = count_query.where(MistakeEntry.parse_status == parse_status)
    query = query.order_by(MistakeEntry.created_at.desc()).offset((page - 1) * size).limit(size)
    items = list((await db.execute(query)).scalars().all())
    total = int((await db.execute(count_query)).scalar_one() or 0)
    return items, total


async def get_mistake(db: AsyncSession, entry_id: str, user_id: str) -> MistakeEntry | None:
    """条目详情（隔离：他人资源统一404）。"""
    result = await db.execute(select(MistakeEntry).where(MistakeEntry.id == entry_id))
    entry = result.scalar_one_or_none()
    if entry is None or entry.user_id != user_id:
        return None
    return entry


async def update_mistake(db: AsyncSession, entry: MistakeEntry, fields: dict) -> None:
    """编辑条目任一字段（§5.8.1规则3，含标签与关联关系）。"""
    for key in ("question", "answer", "error_analysis"):
        if key in fields and fields[key] is not None:
            value = str(fields[key]).strip()
            if not value:
                raise ValueError(f"{key} 不能为空")
            if len(value) > 2000:
                raise ValueError(f"{key} 超过2000字符")
            setattr(entry, key, value)
    if "tags" in fields and fields["tags"] is not None:
        tags = fields["tags"]
        if not isinstance(tags, list) or len(tags) > 10 or any(len(str(t)) > 20 for t in tags):
            raise ValueError("标签须为数组且不超过10个（每个≤20字符）")
        entry.tags = [str(t) for t in tags]
    if "kb_id" in fields:
        entry.kb_id = fields["kb_id"] or None
    if "card_id" in fields:
        entry.card_id = fields["card_id"] or None
    await db.commit()


async def delete_mistake(db: AsyncSession, entry: MistakeEntry) -> None:
    """删除条目（二次确认由前端承担；同时移出一切测验抽取范围，§5.8.1规则3b）。"""
    await db.delete(entry)
    await db.commit()


async def set_mastery(db: AsyncSession, entry: MistakeEntry, mastery: str) -> None:
    """手动更新掌握状态（已掌握可重置回未掌握，禁止静默删除，§5.8.1规则7）。"""
    if mastery not in ("mastered", "unmastered"):
        raise ValueError("掌握状态取值非法")
    entry.mastery = mastery
    await db.commit()


# ---------------- 测验（design §2.1.3.5） ----------------


async def start_quiz(
    db: AsyncSession, user_id: str, strategy: str, count: int, scope: str
) -> tuple[MistakeQuizRecord, list[MistakeEntry]]:
    """发起测验：按策略抽取条目并创建记录（progress=in_progress）。

    - sequential：按录入时间升序（§6.9规则11）
    - random：Python 侧随机抽样（demo体量下等价于 ORDER BY RAND()，且双方言可移植）
    - scope=unmastered 默认仅未掌握；all 含已掌握（§5.8.1规则7）
    - 范围为空抛 EmptyQuizRange（§5.8.3异常3 前置拦截）
    """
    if strategy not in ("sequential", "random"):
        raise ValueError("抽取策略非法")
    if scope not in ("unmastered", "all"):
        raise ValueError("抽取范围非法")
    count = max(1, min(int(count), QUIZ_MAX_COUNT))

    query = select(MistakeEntry).where(MistakeEntry.user_id == user_id)
    if scope == "unmastered":
        query = query.where(MistakeEntry.mastery == "unmastered")
    pool = list((await db.execute(query)).scalars().all())
    if not pool:
        raise EmptyQuizRange()

    if strategy == "random":
        picked = random.sample(pool, min(count, len(pool)))
    else:
        pool.sort(key=lambda e: (e.created_at, e.id))
        picked = pool[:count]

    record = MistakeQuizRecord(
        user_id=user_id,
        strategy=strategy,
        scope={"scope": scope, "count": count},
        entry_ids=[str(e.id) for e in picked],
        marks=[],
        started_at=_now(),
    )
    db.add(record)
    await db.commit()
    return record, picked


def entry_public(entry: MistakeEntry) -> dict:
    """测验中条目的"仅题目"视图（答案揭示前不可见，§5.8.1规则6）。"""
    return {
        "entry_id": str(entry.id),
        "question": entry.question,
        "tags": entry.tags or [],
        "source_type": entry.source_type,
        "obs_key": entry.obs_key,
    }


async def get_quiz(db: AsyncSession, quiz_id: str, user_id: str) -> dict | None:
    """测验状态（中断恢复：返回已答序列+未答题目视图，§5.8.3异常4）。"""
    result = await db.execute(select(MistakeQuizRecord).where(MistakeQuizRecord.id == quiz_id))
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        return None

    marks = record.marks or []
    marked_ids = [m["entry_id"] for m in marks]
    pending_ids = [eid for eid in record.entry_ids if eid not in marked_ids]
    pending_items: list[dict] = []
    if pending_ids:
        entries = (
            await db.execute(select(MistakeEntry).where(MistakeEntry.id.in_(pending_ids)))
        ).scalars().all()
        by_id = {str(e.id): e for e in entries}
        pending_items = [entry_public(by_id[eid]) for eid in pending_ids if eid in by_id]
    return {
        "quiz_id": str(record.id),
        "strategy": record.strategy,
        "scope": record.scope,
        "progress": record.progress,
        "total": len(record.entry_ids),
        "marks": marks,
        "pending": pending_items,
        "started_at": str(record.started_at),
        "ended_at": str(record.ended_at) if record.ended_at else None,
    }


async def submit_answer(
    db: AsyncSession, quiz_id: str, user_id: str, entry_id: str, mark: str
) -> dict:
    """提交单题标记：即时更新条目掌握状态并留存逐题标记（§5.8.1规则6、§6.10规则6）。

    mark: mastered=已掌握 / still_not=仍不会（仍不会→条目保持 unmastered）。
    """
    if mark not in ("mastered", "still_not"):
        raise ValueError("标记取值非法")

    result = await db.execute(select(MistakeQuizRecord).where(MistakeQuizRecord.id == quiz_id))
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        raise QuizNotFound()
    if record.progress != "in_progress":
        raise QuizAlreadyFinished()
    if entry_id not in record.entry_ids:
        raise EntryNotInQuiz()
    # 浅拷贝：JSON列原地append不会被ORM变更检测捕获，必须换新对象再赋值
    marks = list(record.marks or [])
    if any(m["entry_id"] == entry_id for m in marks):
        raise EntryNotInQuiz()

    entry = await get_mistake(db, entry_id, user_id)
    if entry is None:
        raise EntryNotInQuiz()
    entry.mastery = "mastered" if mark == "mastered" else "unmastered"

    marks.append({"entry_id": entry_id, "mark": mark})
    record.marks = marks
    finished = len(marks) >= len(record.entry_ids)
    if finished:
        record.progress = "done"
        record.ended_at = _now()
    await db.commit()
    return {
        "marked": len(marks),
        "total": len(record.entry_ids),
        "finished": finished,
        "entry_mastery": entry.mastery,
    }


async def abandon_quiz(db: AsyncSession, quiz_id: str, user_id: str) -> None:
    """放弃测验：记录置已放弃，已提交的掌握状态更新不回滚（§5.8.3异常4）。"""
    result = await db.execute(select(MistakeQuizRecord).where(MistakeQuizRecord.id == quiz_id))
    record = result.scalar_one_or_none()
    if record is None or record.user_id != user_id:
        raise QuizNotFound()
    if record.progress != "in_progress":
        raise QuizAlreadyFinished()
    record.progress = "abandoned"
    record.ended_at = _now()
    await db.commit()
