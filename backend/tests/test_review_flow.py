# -*- coding: utf-8 -*-
"""复习流程测试（tasks.md 8.2/8.3/14.1）：结构化首排、今日清单、三档自评重算、重复提交409。"""
import uuid

from sqlalchemy import select

from app.models import AsyncTask, KnowledgeCard, ReviewTask
from app.services import card_service


class FakeMaaS:
    async def chat_json(self, messages, **kwargs):
        return {
            "title": "复习测试卡片",
            "summary": "遗忘曲线验证摘要",
            "key_points": ["要点一", "要点二", "要点三"],
            "qa_pairs": [{"question": "什么是遗忘曲线？", "answer": "记忆随时间衰减的规律"}],
            "tags": ["复习"],
        }


async def _setup_card_with_content(client, session_factory, monkeypatch) -> dict:
    """注册→导入→跑structure handler（mock MaaS）→返回 {card_id, task_id}。"""
    import app.services.card_service as cs

    email = f"rev-{uuid.uuid4().hex[:8]}@test.cn"
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": "Passw0rd123"}
    )
    token = resp.json()["data"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    imp = await client.post(
        "/api/assets/text", json={"content": "复习测试内容"}, headers=headers
    )
    task_id = imp.json()["data"]["task_id"]

    monkeypatch.setattr(cs, "get_maas_client", lambda: FakeMaaS())
    async with session_factory() as db:
        task = (await db.execute(select(AsyncTask).where(AsyncTask.id == task_id))).scalar_one()
        await card_service.structure_task_handler(db, task)

    async with session_factory() as db:
        card = (
            await db.execute(
                select(KnowledgeCard).where(KnowledgeCard.asset_id == imp.json()["data"]["asset_id"])
            )
        ).scalar_one()
    return {"token": token, "task_id": task_id, "card_id": card.id}


async def test_structure_schedules_first_review(client, session_factory, monkeypatch):
    """结构化成功后出现次日 pending 首排任务（spec §5.6.1规则1）。"""
    from datetime import date, timedelta

    ctx = await _setup_card_with_content(client, session_factory, monkeypatch)
    async with session_factory() as db:
        tasks = (
            await db.execute(
                select(ReviewTask).where(
                    ReviewTask.card_id == ctx["card_id"], ReviewTask.status == "pending"
                )
            )
        ).scalars().all()
        assert len(tasks) == 1
        assert tasks[0].planned_date == date.today() + timedelta(days=1)


async def test_today_list_empty_before_due(client, session_factory, monkeypatch):
    """首排任务在明天 → 今日清单为空。"""
    ctx = await _setup_card_with_content(client, session_factory, monkeypatch)
    resp = await client.get("/api/reviews/today", headers={"Authorization": f"Bearer {ctx['token']}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0


async def test_today_list_and_submit_rating(client, session_factory, monkeypatch):
    """到期任务出现在今日清单；提交"记住"后间隔升档、次日任务生成。"""
    from datetime import date, timedelta

    ctx = await _setup_card_with_content(client, session_factory, monkeypatch)
    headers = {"Authorization": f"Bearer {ctx['token']}"}

    # 手动插入一条今日到期任务
    async with session_factory() as db:
        db.add(
            ReviewTask(
                card_id=ctx["card_id"],
                user_id=await _user_id(client, headers),
                planned_date=date.today(),
                status="pending",
            )
        )
        await db.commit()

    today = await client.get("/api/reviews/today", headers=headers)
    items = today.json()["data"]["items"]
    assert today.json()["data"]["total"] == 1
    assert items[0]["qa_pairs"][0]["question"] == "什么是遗忘曲线？"

    task_id = items[0]["task_id"]
    submit = await client.post(
        f"/api/reviews/{task_id}/submit", json={"rating": "remember"}, headers=headers
    )
    assert submit.status_code == 200
    result = submit.json()["data"]
    assert result["next_interval_days"] == 2  # 首排1天 + 记住 → 升到2天档
    assert result["next_review_date"] == (date.today() + timedelta(days=2)).isoformat()

    # 今日清单清空（今日任务done、下次任务在明天）
    today2 = await client.get("/api/reviews/today", headers=headers)
    assert today2.json()["data"]["total"] == 0


async def test_rating_forget_resets_interval(client, session_factory, monkeypatch):
    """自评"忘记"→ 间隔重置1天、次日重回列表。"""
    from datetime import date, timedelta

    ctx = await _setup_card_with_content(client, session_factory, monkeypatch)
    headers = {"Authorization": f"Bearer {ctx['token']}"}

    async with session_factory() as db:
        db.add(
            ReviewTask(
                card_id=ctx["card_id"],
                user_id=await _user_id(client, headers),
                planned_date=date.today(),
                status="pending",
            )
        )
        await db.commit()

    items = (await client.get("/api/reviews/today", headers=headers)).json()["data"]["items"]
    submit = await client.post(
        f"/api/reviews/{items[0]['task_id']}/submit", json={"rating": "forget"}, headers=headers
    )
    assert submit.status_code == 200
    assert submit.json()["data"]["next_interval_days"] == 1
    assert submit.json()["data"]["next_review_date"] == (date.today() + timedelta(days=1)).isoformat()


async def test_invalid_rating_422_and_repeated_submit_409(client, session_factory, monkeypatch):
    from datetime import date

    ctx = await _setup_card_with_content(client, session_factory, monkeypatch)
    headers = {"Authorization": f"Bearer {ctx['token']}"}

    async with session_factory() as db:
        db.add(
            ReviewTask(
                card_id=ctx["card_id"],
                user_id=await _user_id(client, headers),
                planned_date=date.today(),
                status="pending",
            )
        )
        await db.commit()

    items = (await client.get("/api/reviews/today", headers=headers)).json()["data"]["items"]
    task_id = items[0]["task_id"]

    bad = await client.post(
        f"/api/reviews/{task_id}/submit", json={"rating": "excellent"}, headers=headers
    )
    assert bad.status_code == 422

    good = await client.post(
        f"/api/reviews/{task_id}/submit", json={"rating": "blur"}, headers=headers
    )
    assert good.status_code == 200

    dup = await client.post(
        f"/api/reviews/{task_id}/submit", json={"rating": "blur"}, headers=headers
    )
    assert dup.status_code == 409


async def test_other_users_task_404(client, session_factory, monkeypatch):
    ctx = await _setup_card_with_content(client, session_factory, monkeypatch)
    other = await client.post(
        "/api/auth/register",
        json={"email": f"other-{uuid.uuid4().hex[:6]}@t.cn", "password": "Passw0rd123"},
    )
    other_headers = {"Authorization": f"Bearer {other.json()['data']['token']}"}
    resp = await client.post(
        f"/api/reviews/{ctx['card_id']}/submit", json={"rating": "remember"}, headers=other_headers
    )
    assert resp.status_code == 404


async def _user_id(client, headers) -> str:
    me = await client.get("/api/auth/me", headers=headers)
    return me.json()["data"]["id"]
