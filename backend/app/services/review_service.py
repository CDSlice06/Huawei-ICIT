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
            ReviewTask.status.in_(["pending", "postponed"]),
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

    # 写穿更新复习统计（design §2.2.2.6 submit后置：更新复习统计）
    await refresh_statistics(db, user_id)
    await redis_client.cache_delete(review_today_cache_key(user_id))
    return {
        "rating": rating,
        "next_interval_days": next_interval,
        "next_review_date": next_task.planned_date.isoformat(),
        "next_task_id": str(next_task.id),
    }


TREND_DAYS = 14  # 遗忘趋势回看窗口（spec §6.7规则2 按日/周）


async def refresh_statistics(db: AsyncSession, user_id: str) -> dict:
    """重算并持久化用户复习统计（spec §6.7：由完成记录聚合派生）。

    - total_reviews：已完成复习任务数
    - mastered_count / consolidating_count：按每张卡片最近一次自评归类
      （记住→已掌握；模糊/忘记→待巩固，spec §6.7规则2）
    - trend_data：近14天每日完成数与"记住"数
    """
    from datetime import timedelta

    from app.models import ReviewStatistics

    done_result = await db.execute(
        select(ReviewTask)
        .where(ReviewTask.user_id == user_id, ReviewTask.status == "done")
        .order_by(ReviewTask.completed_at.asc())
    )
    done_tasks = done_result.scalars().all()
    total_reviews = len(done_tasks)

    # 每卡最近一次自评
    latest_rating: dict[str, str] = {}
    for rt in done_tasks:
        if rt.rating and rt.card_id:
            latest_rating[str(rt.card_id)] = rt.rating
    mastered = sum(1 for r in latest_rating.values() if r == "remember")
    consolidating = sum(1 for r in latest_rating.values() if r in ("blur", "forget"))

    # 近14天趋势（UTC日界，与排定口径一致）
    today = _today()
    trend: list[dict] = []
    for offset in range(TREND_DAYS - 1, -1, -1):
        day = today - timedelta(days=offset)
        day_done = [rt for rt in done_tasks if rt.completed_at and rt.completed_at.date() == day]
        trend.append({
            "date": day.isoformat(),
            "done": len(day_done),
            "remember": sum(1 for rt in day_done if rt.rating == "remember"),
        })

    result = await db.execute(select(ReviewStatistics).where(ReviewStatistics.user_id == user_id))
    stats = result.scalar_one_or_none()
    if stats is None:
        stats = ReviewStatistics(user_id=user_id)
        db.add(stats)
    stats.total_reviews = total_reviews
    stats.mastered_count = mastered
    stats.consolidating_count = consolidating
    stats.trend_data = trend
    await db.commit()
    return {
        "total_reviews": total_reviews,
        "mastered_count": mastered,
        "consolidating_count": consolidating,
        "trend_data": trend,
        "streak_days": stats.streak_days,
    }


async def postpone_overdue_tasks(db: AsyncSession) -> int:
    """逾期复习顺延（P1-7b，design §2.7.4、spec §6.5规则4）。

    每日1:00：扫描 planned_date < 今日 且仍 pending 的任务 → 置"已顺延"，
    计划日期改为当天（不删除，今日清单继续可见）。
    """
    from sqlalchemy import update

    today = _today()
    result = await db.execute(
        select(ReviewTask).where(ReviewTask.status == "pending", ReviewTask.planned_date < today)
    )
    overdue = result.scalars().all()
    if not overdue:
        return 0
    affected_users: set[str] = set()
    for rt in overdue:
        rt.status = "postponed"
        rt.planned_date = today
        affected_users.add(str(rt.user_id))
    await db.commit()
    for uid in affected_users:
        await redis_client.cache_delete(review_today_cache_key(uid))
    return len(overdue)