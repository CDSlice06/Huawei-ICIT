"""演示账号服务（tasks.md 9.1/9.2，spec §5.1.1规则5~6）。"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AsyncTask,
    KnowledgeAsset,
    KnowledgeBase,
    KnowledgeCard,
    MapNode,
    MindMap,
    ReviewTask,
    User,
)


class DemoAccountNotConfigured(Exception):
    """演示账号环境变量未配置。"""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _today() -> date:
    return datetime.now(timezone.utc).date()


async def _get_demo_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.email == settings.DEMO_ACCOUNT_EMAIL))
    user = result.scalar_one_or_none()
    if user is None:
        raise DemoAccountNotConfigured("演示账号不存在，请先运行 seed_demo 脚本")
    return user


async def _purge_demo_data(db: AsyncSession, user_id: str) -> None:
    """清空演示账号全部业务数据（幂等重置前置步骤）。"""
    cards = await db.execute(select(KnowledgeCard).where(KnowledgeCard.user_id == user_id))
    card_ids = [c.id for c in cards.scalars().all()]
    if card_ids:
        await db.execute(delete(ReviewTask).where(ReviewTask.card_id.in_(card_ids)))
    await db.execute(delete(ReviewTask).where(ReviewTask.user_id == user_id))
    await db.execute(delete(AsyncTask).where(AsyncTask.user_id == user_id))
    await db.execute(delete(KnowledgeAsset).where(KnowledgeAsset.user_id == user_id))
    maps = await db.execute(select(MindMap).join(KnowledgeBase, MindMap.kb_id == KnowledgeBase.id).where(KnowledgeBase.user_id == user_id))
    map_ids = [m.id for m in maps.scalars().all()]
    if map_ids:
        await db.execute(delete(MapNode).where(MapNode.map_id.in_(map_ids)))
        await db.execute(delete(MindMap).where(MindMap.id.in_(map_ids)))
    await db.execute(
        delete(KnowledgeCard).where(KnowledgeCard.user_id == user_id)
    )
    await db.execute(delete(KnowledgeBase).where(KnowledgeBase.user_id == user_id))


async def _seed_data(db: AsyncSession, user: User) -> dict:
    """预置示例数据：2个知识库+卡片+导图+今日待复习任务。"""
    today = _today()
    stats = {"kbs": 0, "cards": 0, "maps": 0, "review_tasks": 0}

    demo_sets = [
        {
            "kb_name": "读书笔记",
            "cards": [
                {
                    "title": "《思考，快与慢》核心观点",
                    "summary": "人类思维存在系统1（快直觉）与系统2（慢理性）两套模式。",
                    "key_points": [
                        "系统1快速直觉但易受偏差影响",
                        "系统2耗能理性但常被系统1接管",
                        "锚定效应让首个数字影响后续判断",
                    ],
                    "qa_pairs": [{"question": "系统1和系统2的区别是什么？", "answer": "系统1快而直觉、系统2慢而理性"}],
                    "tags": ["读书笔记", "心理学"],
                },
                {
                    "title": "《刻意练习》方法论",
                    "summary": "高手依赖有目的的刻意练习而非单纯天赋。",
                    "key_points": [
                        "练习需走出舒适区",
                        "即时反馈是进步关键",
                        "心理表征决定专业水平",
                    ],
                    "qa_pairs": [{"question": "刻意练习的三要素？", "answer": "走出舒适区、即时反馈、构建心理表征"}],
                    "tags": ["读书笔记", "方法论"],
                },
            ],
        },
        {
            "kb_name": "Python入门",
            "cards": [
                {
                    "title": "Python列表与元组",
                    "summary": "列表可变、元组不可变，是Python最常用的序列类型。",
                    "key_points": [
                        "列表用方括号、元组用圆括号",
                        "元组可作字典键，列表不可",
                        "列表推导式是常用语法糖",
                    ],
                    "qa_pairs": [{"question": "列表和元组的区别？", "answer": "列表可变，元组不可变且可哈希"}],
                    "tags": ["编程", "Python"],
                },
            ],
        },
    ]

    for spec in demo_sets:
        kb = KnowledgeBase(user_id=user.id, name=spec["kb_name"], created_at=_now())
        db.add(kb)
        await db.flush()
        stats["kbs"] += 1

        card_ids: list[str] = []
        for cd in spec["cards"]:
            card = KnowledgeCard(
                user_id=user.id,
                kb_id=kb.id,
                title=cd["title"],
                summary=cd["summary"],
                key_points=cd["key_points"],
                qa_pairs=cd["qa_pairs"],
                tags=cd["tags"],
                review_interval_days=1,
                review_count=0,
                created_at=_now(),
            )
            # asset_id NOT NULL：为演示数据创建对应素材记录
            asset = KnowledgeAsset(
                user_id=user.id,
                kb_id=kb.id,
                type="text",
                raw_content=cd["summary"],
                extracted_text=cd["summary"],
                parse_status="done",
                created_at=_now(),
            )
            db.add(asset)
            await db.flush()
            card.asset_id = asset.id
            db.add(card)
            await db.flush()
            card_ids.append(card.id)
            stats["cards"] += 1

            # 部分待复习任务 planned_date=今日（保证"今日待回顾"非空）
            rt = ReviewTask(
                card_id=card.id,
                user_id=user.id,
                planned_date=today if len(card_ids) % 2 == 1 else today + timedelta(days=1),
                status="pending",
            )
            db.add(rt)
            stats["review_tasks"] += 1

            # 少量已完成历史任务（体现复习历史，spec §5.1.1规则5）
            if stats["cards"] % 2 == 0:
                history = ReviewTask(
                    card_id=card.id,
                    user_id=user.id,
                    planned_date=today - timedelta(days=2),
                    status="done",
                    rating="remember",
                    completed_at=_now() - timedelta(days=2),
                )
                db.add(history)

        # 每库构建简单两层导图（auto版本，节点无坐标→前端默认布局）
        mp = MindMap(kb_id=kb.id, version_source="auto", created_at=_now())
        db.add(mp)
        await db.flush()
        root = MapNode(map_id=mp.id, parent_id=None, title=spec["kb_name"], pos_x=None, pos_y=None)
        db.add(root)
        await db.flush()
        for i, cid in enumerate(card_ids):
            node = MapNode(
                map_id=mp.id,
                parent_id=root.id,
                title=spec["cards"][i]["title"][:50],
                card_id=cid,
                pos_x=None,
                pos_y=None,
            )
            db.add(node)
        stats["maps"] += 1

    await db.commit()
    return stats


async def seed_demo_account(db: AsyncSession) -> dict:
    """幂等预置演示账号（已存在则清空重建，tasks.md 9.1）。"""
    from app.services import auth_service

    user = await auth_service.get_user_by_email(db, settings.DEMO_ACCOUNT_EMAIL)
    if user is None:
        user, _ = await auth_service.register(db, settings.DEMO_ACCOUNT_EMAIL, settings.DEMO_ACCOUNT_PASSWORD)
        user.is_demo = 1
        await db.commit()
    else:
        await _purge_demo_data(db, user.id)

    stats = await _seed_data(db, user)
    return {"email": user.email, **stats}


async def reset_demo_account(db: AsyncSession) -> dict:
    """演示账号数据重置：清空+重建（spec §5.1.1规则6）。"""
    user = await _get_demo_user(db)
    await _purge_demo_data(db, user.id)
    stats = await _seed_data(db, user)
    return {"email": user.email, **stats}


def reset_demo_account_sync() -> dict:
    """同步入口（APScheduler cron job 调用）。"""
    import asyncio

    from app.db import AsyncSessionLocal

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            return await reset_demo_account(db)

    return asyncio.run(_run())