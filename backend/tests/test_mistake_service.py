# -*- coding: utf-8 -*-
"""错题本与错题测验测试（P1-1，tasks.md 1.1g；spec §5.8、§6.9~§6.10）。

覆盖：解析校验不落残缺条目、文本/图片解析handler、CRUD与掌握状态、
测验抽取策略与范围、"先题目后揭示"交互、逐题标记状态机、中断恢复、数据隔离。
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import app.services.mistake_service as ms
from app.models import MistakeEntry, MistakeQuizRecord
from app.services.mistake_service import MistakeSchemaError, _validate_mistake_schema


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FakeMistakeMaaS:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {
            "question": "勾股定理的内容是什么？",
            "answer": "a²+b²=c²",
            "error_analysis": "混淆了斜边与直角边",
            "tags": ["数学", "计算错误"],
        }
        self.error = error
        self.calls = []

    async def chat_json(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self.error:
            raise self.error
        return self.payload


def _valid_parsed(question="勾股定理的内容是什么？"):
    return {
        "question": question,
        "answer": "a²+b²=c²",
        "error_analysis": "混淆了斜边与直角边",
        "tags": ["数学", "计算错误"],
    }


# ---------------- 解析输出校验（§6.9、§5.8.3异常2） ----------------


def test_validate_schema_accepts_minimal():
    data = _validate_mistake_schema(
        {"question": "题", "answer": "答", "error_analysis": "析", "tags": []}
    )
    assert data["tags"] == []


def test_validate_schema_rejects_missing_core_fields():
    for field in ("question", "answer", "error_analysis"):
        payload = _valid_parsed()
        payload[field] = "  "
        with pytest.raises(MistakeSchemaError, match="缺失"):
            _validate_mistake_schema(payload)


def test_validate_schema_rejects_overlong_and_bad_tags():
    with pytest.raises(MistakeSchemaError, match="2000"):
        _validate_mistake_schema(_valid_parsed("长" * 2001))
    with pytest.raises(MistakeSchemaError, match="标签"):
        _validate_mistake_schema({**_valid_parsed(), "tags": [f"t{i}" for i in range(11)]})
    with pytest.raises(MistakeSchemaError, match="20字符"):
        _validate_mistake_schema({**_valid_parsed(), "tags": ["超长标签" * 10]})


# ---------------- 解析 handler（1.1b） ----------------


async def test_text_parse_handler_fills_fields(session_factory, kb_with_user, monkeypatch):
    ctx = kb_with_user
    monkeypatch.setattr(ms, "get_maas_client", lambda: FakeMistakeMaaS())
    async with session_factory() as db:
        entry, task = await ms.create_text_mistake(db, ctx["user_id"], "题目原文：勾股定理")
        result = await ms.mistake_parse_task_handler(db, task)

    async with session_factory() as db:
        fresh = await db.get(MistakeEntry, entry.id)
        assert fresh.parse_status == "done"
        assert fresh.question == "勾股定理的内容是什么？"
        assert fresh.answer == "a²+b²=c²"
        assert fresh.error_analysis and fresh.tags == ["数学", "计算错误"]
        assert fresh.source_type == "text" and fresh.mastery == "unmastered"


async def test_parse_failure_preserves_raw(session_factory, kb_with_user, monkeypatch):
    """解析失败：parse_status=failed、原文保留、无残缺条目字段（§5.8.3异常2）。"""
    ctx = kb_with_user
    monkeypatch.setattr(
        ms, "get_maas_client", lambda: FakeMistakeMaaS(error=ms.MaasError("模型超时"))
    )
    async with session_factory() as db:
        entry, task = await ms.create_text_mistake(db, ctx["user_id"], "保留的原文")
        with pytest.raises(ms.MaasError):
            await ms.mistake_parse_task_handler(db, task)

    async with session_factory() as db:
        fresh = await db.get(MistakeEntry, entry.id)
        assert fresh.parse_status == "failed"
        assert fresh.raw_content == "保留的原文"  # 原文不丢失
        assert fresh.answer == ""  # 未落残缺解析结果


async def test_image_parse_uses_multimodal_and_obs_url(session_factory, kb_with_user, monkeypatch):
    """图片录入：多模态一次调用（120s），图片URL来自OBS配置（§5.8.1规则1）。"""
    ctx = kb_with_user
    fake = FakeMistakeMaaS()
    monkeypatch.setattr(ms, "get_maas_client", lambda: fake)
    monkeypatch.setattr(
        "app.infrastructure.obs_client.image_access_url",
        lambda obs_key: f"https://bucket.obs.example.com/{obs_key}",
    )
    async with session_factory() as db:
        entry, task = await ms.create_image_mistake(db, ctx["user_id"], "mistakes/img-1.jpg")
        await ms.mistake_parse_task_handler(db, task)

    assert fake.calls and fake.calls[0].get("multimodal") is True
    content = fake.calls[0]["messages"][1]["content"]
    assert content[1]["image_url"]["url"].endswith("/mistakes/img-1.jpg")


async def test_image_parse_without_obs_fails_gracefully(session_factory, kb_with_user, monkeypatch):
    """OBS未配置：明确报错、条目置failed（改用文本录入路径仍可用）。"""
    ctx = kb_with_user
    monkeypatch.setattr("app.config.settings.OBS_ENDPOINT", "")
    monkeypatch.setattr(ms, "get_maas_client", lambda: FakeMistakeMaaS())
    async with session_factory() as db:
        entry, task = await ms.create_image_mistake(db, ctx["user_id"], "mistakes/img-2.jpg")
        with pytest.raises(ms.MaasError, match="OBS"):
            await ms.mistake_parse_task_handler(db, task)
    async with session_factory() as db:
        fresh = await db.get(MistakeEntry, entry.id)
        assert fresh.parse_status == "failed"


# ---------------- 测验（1.1d，design §2.1.3.5） ----------------


async def test_quiz_sequential_and_scope(session_factory, kb_with_user, client, auth_headers, no_submit):
    """按顺序抽取=录入时间升序；默认范围仅未掌握（§5.8.1规则5/7）。"""
    ctx = kb_with_user
    async with session_factory() as db:
        base = _now() - timedelta(minutes=10)
        for i in range(3):
            db.add(
                MistakeEntry(
                    user_id=ctx["user_id"], question=f"题{i}", answer="答", error_analysis="析",
                    source_type="text", mastery="unmastered", parse_status="done",
                    created_at=base + timedelta(minutes=i),
                )
            )
        db.add(
            MistakeEntry(
                user_id=ctx["user_id"], question="已掌握题", answer="答", error_analysis="析",
                source_type="text", mastery="mastered", parse_status="done", created_at=base,
            )
        )
        await db.commit()

    resp = await client.post(
        "/api/mistakes/quiz",
        json={"strategy": "sequential", "count": 10, "scope": "unmastered"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["total"] == 3  # 已掌握条目不在默认范围
    assert "answer" not in data["items"][0] and "error_analysis" not in data["items"][0]
    questions = [item["question"] for item in data["items"]]
    assert questions == ["题0", "题1", "题2"]  # created_at 升序


async def test_quiz_random_within_count(session_factory, kb_with_user, client, auth_headers):
    ctx = kb_with_user
    async with session_factory() as db:
        for i in range(8):
            db.add(
                MistakeEntry(
                    user_id=ctx["user_id"], question=f"题{i}", answer="答", error_analysis="析",
                    source_type="text", parse_status="done", created_at=_now(),
                )
            )
        await db.commit()

    resp = await client.post(
        "/api/mistakes/quiz", json={"strategy": "random", "count": 5, "scope": "all"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["total"] == 5


async def test_quiz_empty_range_422(client, auth_headers):
    resp = await client.post(
        "/api/mistakes/quiz", json={"strategy": "sequential", "count": 10, "scope": "unmastered"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "范围" in resp.json()["message"]


async def test_quiz_answer_flow_updates_mastery(session_factory, kb_with_user, client, auth_headers):
    """揭示→标记：条目掌握状态即时更新；全部标记后测验完成（§5.8.1规则6）。"""
    ctx = kb_with_user
    async with session_factory() as db:
        e1 = MistakeEntry(
            user_id=ctx["user_id"], question="题1", answer="答1", error_analysis="析1",
            source_type="text", parse_status="done", created_at=_now(),
        )
        e2 = MistakeEntry(
            user_id=ctx["user_id"], question="题2", answer="答2", error_analysis="析2",
            source_type="text", parse_status="done", created_at=_now(),
        )
        db.add_all([e1, e2])
        await db.commit()
        e1_id, e2_id = str(e1.id), str(e2.id)

    quiz = (
        await client.post(
            "/api/mistakes/quiz", json={"strategy": "sequential", "count": 2, "scope": "all"},
            headers=auth_headers,
        )
    ).json()["data"]
    quiz_id = quiz["quiz_id"]

    # 揭示答案经条目详情接口
    detail = await client.get(f"/api/mistakes/{e1_id}", headers=auth_headers)
    assert detail.json()["data"]["answer"] == "答1"

    # 标记"已掌握"→条目即时更新
    r1 = await client.post(
        f"/api/mistakes/quiz/{quiz_id}/answer", json={"entry_id": e1_id, "mark": "mastered"},
        headers=auth_headers,
    )
    assert r1.status_code == 200
    assert r1.json()["data"]["entry_mastery"] == "mastered"
    assert r1.json()["data"]["finished"] is False

    # 标记"仍不会"→保持未掌握
    r2 = await client.post(
        f"/api/mistakes/quiz/{quiz_id}/answer", json={"entry_id": e2_id, "mark": "still_not"},
        headers=auth_headers,
    )
    assert r2.json()["data"]["finished"] is True

    async with session_factory() as db:
        assert (await db.get(MistakeEntry, e1_id)).mastery == "mastered"
        assert (await db.get(MistakeEntry, e2_id)).mastery == "unmastered"
        record = (await db.execute(select(MistakeQuizRecord).where(MistakeQuizRecord.id == quiz_id))).scalar_one()
        assert record.progress == "done" and len(record.marks) == 2

    # 已完成测验不可重复作答/放弃
    assert (
        await client.post(f"/api/mistakes/quiz/{quiz_id}/answer", json={"entry_id": e1_id, "mark": "still_not"}, headers=auth_headers)
    ).status_code == 409
    assert (
        await client.patch(f"/api/mistakes/quiz/{quiz_id}/status", json={"status": "abandoned"}, headers=auth_headers)
    ).status_code == 409


async def test_quiz_resume_and_abandon_keeps_marks(session_factory, kb_with_user, client, auth_headers):
    """中断恢复：GET进度返回未答题目；放弃后已提交标记不回滚（§5.8.3异常4）。"""
    ctx = kb_with_user
    async with session_factory() as db:
        entries = [
            MistakeEntry(
                user_id=ctx["user_id"], question=f"题{i}", answer=f"答{i}", error_analysis="析",
                source_type="text", parse_status="done", created_at=_now(),
            )
            for i in range(3)
        ]
        db.add_all(entries)
        await db.commit()
        ids = [str(e.id) for e in entries]

    quiz = (
        await client.post(
            "/api/mistakes/quiz", json={"strategy": "sequential", "count": 3, "scope": "all"},
            headers=auth_headers,
        )
    ).json()["data"]
    quiz_id = quiz["quiz_id"]

    # 答第1题后"中断"
    await client.post(f"/api/mistakes/quiz/{quiz_id}/answer", json={"entry_id": ids[0], "mark": "still_not"}, headers=auth_headers)
    state = (await client.get(f"/api/mistakes/quiz/{quiz_id}", headers=auth_headers)).json()["data"]
    assert state["progress"] == "in_progress" and state["total"] == 3
    assert len(state["marks"]) == 1 and len(state["pending"]) == 2
    assert "answer" not in state["pending"][0]  # 未揭示的答案不下发

    # 放弃：已提交的掌握状态不回滚
    assert (
        await client.patch(f"/api/mistakes/quiz/{quiz_id}/status", json={"status": "abandoned"}, headers=auth_headers)
    ).status_code == 200
    async with session_factory() as db:
        record = (await db.execute(select(MistakeQuizRecord).where(MistakeQuizRecord.id == quiz_id))).scalar_one()
        assert record.progress == "abandoned" and len(record.marks) == 1
        assert (await db.get(MistakeEntry, ids[0])).mastery == "unmastered"


# ---------------- 录入接口与隔离 ----------------


async def test_text_import_202_and_gate(client, auth_headers, no_submit):
    ok1 = await client.post("/api/mistakes/text", json={"content": "错题内容"}, headers=auth_headers)
    assert ok1.status_code == 202
    assert ok1.json()["data"]["task_id"] and ok1.json()["data"]["mistake_id"]
    over = await client.post("/api/mistakes/text", json={"content": "长" * 5001}, headers=auth_headers)
    assert over.status_code == 422
    third = await client.post("/api/mistakes/text", json={"content": "再录一条"}, headers=auth_headers)
    assert third.status_code == 202
    fourth = await client.post("/api/mistakes/text", json={"content": "第四条"}, headers=auth_headers)
    assert fourth.status_code == 429  # 并发闸门合并计数（mistake_parse + structure）


async def test_mistake_isolation_and_mastery_reset(session_factory, kb_with_user, client, auth_headers):
    ctx = kb_with_user
    async with session_factory() as db:
        entry = MistakeEntry(
            user_id=ctx["user_id"], question="题", answer="答", error_analysis="析",
            source_type="text", parse_status="done", created_at=_now(),
        )
        db.add(entry)
        await db.commit()
        entry_id = str(entry.id)

    other = await client.post(
        "/api/auth/register", json={"email": f"m-{uuid.uuid4().hex[:6]}@t.cn", "password": "Passw0rd123"}
    )
    other_headers = {"Authorization": f"Bearer {other.json()['data']['token']}"}
    assert (await client.get(f"/api/mistakes/{entry_id}", headers=other_headers)).status_code == 404
    assert (
        await client.patch(f"/api/mistakes/{entry_id}/mastery", json={"mastery": "mastered"}, headers=other_headers)
    ).status_code == 404
    assert (await client.delete(f"/api/mistakes/{entry_id}", headers=other_headers)).status_code == 404

    # 本人：掌握→重置回未掌握（§5.8.1规则7b），非法取值422
    assert (
        await client.patch(f"/api/mistakes/{entry_id}/mastery", json={"mastery": "mastered"}, headers=auth_headers)
    ).json()["data"]["mastery"] == "mastered"
    assert (
        await client.patch(f"/api/mistakes/{entry_id}/mastery", json={"mastery": "unmastered"}, headers=auth_headers)
    ).json()["data"]["mastery"] == "unmastered"
    assert (
        await client.patch(f"/api/mistakes/{entry_id}/mastery", json={"mastery": "maybe"}, headers=auth_headers)
    ).status_code == 422


async def test_mistake_edit_and_delete(session_factory, kb_with_user, client, auth_headers):
    ctx = kb_with_user
    async with session_factory() as db:
        entry = MistakeEntry(
            user_id=ctx["user_id"], question="原题", answer="答", error_analysis="析",
            source_type="text", parse_status="done", created_at=_now(),
        )
        db.add(entry)
        await db.commit()
        entry_id = str(entry.id)

    # 编辑错因解析即时生效（§5.8.1规则3a）
    put = await client.put(
        f"/api/mistakes/{entry_id}",
        json={"error_analysis": "审题不仔细", "tags": ["审题"]},
        headers=auth_headers,
    )
    assert put.status_code == 200
    assert put.json()["data"]["error_analysis"] == "审题不仔细"
    # 空字段422
    assert (
        await client.put(f"/api/mistakes/{entry_id}", json={"answer": "  "}, headers=auth_headers)
    ).status_code == 422

    # 删除后从错题本消失（§5.8.1规则3b）
    assert (
        await client.delete(f"/api/mistakes/{entry_id}", headers=auth_headers)
    ).status_code == 200
    async with session_factory() as db:
        assert (await db.get(MistakeEntry, entry_id)) is None
