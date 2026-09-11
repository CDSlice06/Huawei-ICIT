"""复习服务（tasks.md 8.2/8.3，spec §5.6.1）。"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms import spaced_repetition
from app.infrastructure import redis_client
from app.models import AsyncTask, KnowledgeCard, ReviewTask


class TaskNotFound(Exception):
    """复习任务不存在或无权访问。"""


class TaskAlreadyDone(Exception):
    """任务已完成，重复提交（spec §5.6.3）。"""


class InvalidRating(Exception):
    """非法自评值。"""


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def review_today_cache_key(user_id: str) -> str:
    return redis_client.KEY_REVIEW_TODAY.format(user_id=user_id, date=_today().isoformat())


async def schedule_first_review(db: AsyncSession, card: KnowledgeCard) -> None:
    """卡片创建成功即排定首次复习任务（spec §5.6.1规则1）。

    planned_date = 创建日 + 1天（design.md §2.1.3.2 首次排定）。
    """
    db.add(
        ReviewTask(
            card_id=card.id,
            user_id=card.user_id,
            planned_date=_today() + timedelta(days=spaced_repetition.first_interval()),
            status="pending",
        )
    )
    await db.flush()


async def list_today_tasks(db: AsyncSession, user_id: str) -> list[dict]:
    """今日待复习清单（JOIN卡片返回标题/问答对，Redis缓存 TTL 10min，spec §5.6.1规则3）。"""
    import json

    key = review_today_cache_key(user_id)
    cached = await redis_client.cache_get(key)
    if cached:
        return json.loads(cached)

    today = _today()
    result = await db.execute(
        select(ReviewTask, KnowledgeCard)
        .join(KnowledgeCard, ReviewTask.card_id == KnowledgeCard.id)
        .where(
            ReviewTask.user_id == user_id,
            ReviewTask.planned_date <= today,
            ReviewTask.status == "pending",
        )
        .order_by(ReviewTask.planned_date.asc(), ReviewTask.completed_at.asc())
        .limit(200)
    )
    items = []
    for rt, card in result.all():
        items.append({
            "task_id": str(rt.id),
            "card_id": str(card.id),
            "title": card.title,
            "qa_pairs": card.qa_pairs,
            "planned_date": rt.planned_date.isoformat(),
            "overdue": rt.planned_date < today,
        })
    await redis_client.cache_set(key, json.dumps(items, ensure_ascii=False), ttl=600)
    return items


async def submit_rating(
    db: AsyncSession, user_id: str, task_id: str, rating: str
) -> dict:
    """提交掌握度自评（spec §5.6.1规则2、§6.5规则4~5）。

    忘记→重置间隔1天；模糊→保持当前档；记住→升一档。
    完成当前任务并排定下次任务。
    """
    if rating not in ("forget", "blur", "remember"):
        raise InvalidRating()

    result = await db.execute(select(ReviewTask).where(ReviewTask.id == task_id))
    rt = result.scalar_one_or_none()
    if rt is None or rt.user_id != user_id:
        raise TaskNotFound()
    if rt.status == "done":
        raise TaskAlreadyDone()

    card_result = await db.execute(select(KnowledgeCard).where(KnowledgeCard.id == rt.card_id))
    card = card_result.scalar_one_or_none()
    if card is None:
        raise TaskNotFound()

    next_interval, next_count = spaced_repetition.next_review(
        card.review_interval_days, card.review_count, rating
    )

    rt.status = "done"
    rt.rating = rating
    rt.completed_at = _now()

    card.review_interval_days = next_interval
    card.review_count = next_count

    next_task = ReviewTask(
        card_id=card.id,
        user_id=user_id,
        planned_date=_today() + timedelta(days=next_interval),
        status="pending",
    )
    db.add(next_task)
    await db.commit()

    await redis_client.cache_delete(review_today_cache_key(user_id))
    return {
        "rating": rating,
        "next_interval_days": next_interval,
        "next_review_date": next_task.planned_date.isoformat(),
        "next_task_id": str(next_task.id),
    }