# -*- coding: utf-8 -*-
"""文档/图片导入测试（P1-2/P1-3，tasks.md 1.2/1.3）。

覆盖：presign 双模式（OBS签名/本地代存回退）、multipart上传校验、
PDF/DOCX 正文提取、文档→结构化全链路（mock MaaS）、图片多模态路径、隔离。
"""
import io
import uuid

import pytest
from sqlalchemy import select

import app.services.card_service as cs
from app.models import AsyncTask, KnowledgeAsset, KnowledgeCard


class FakeCardMaaS:
    """记录调用并返回固定卡片JSON（支持单卡/多卡）。"""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def chat_json(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        return self.payload


def _card_payload(title="测试卡片"):
    return {
        "title": title,
        "summary": "这是一份摘要内容。",
        "key_points": ["要点一", "要点二", "要点三"],
        "qa_pairs": [{"question": "问题？", "answer": "答案"}],
        "tags": ["标签1"],
    }


def _make_pdf(text: str) -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    return doc.tobytes()


def _make_docx(text: str) -> bytes:
    from docx import Document

    buf = io.BytesIO()
    doc = Document()
    doc.add_paragraph(text)
    doc.save(buf)
    return buf.getvalue()


async def _upload(client, auth_headers, kind: str, filename: str, data: bytes) -> dict:
    """presign → 本地代存上传 → 返回 {obs_key}。"""
    presign = await client.get(
        "/api/obs/presign",
        params={"filename": filename, "content_type": "application/octet-stream", "kind": kind},
        headers=auth_headers,
    )
    assert presign.status_code == 200
    ticket = presign.json()["data"]
    assert ticket["mode"] == "local"  # 未配置OBS → 本地回退
    assert ticket["obs_key"].count("/") == 2

    upload = await client.post(
        ticket["upload_url"],
        params={"obs_key": ticket["obs_key"]},
        files={"file": (filename, data)},
        headers=auth_headers,
    )
    assert upload.status_code == 200, upload.text
    return ticket


async def _run_structure_task(session_factory, task_id: str, mock: FakeCardMaaS, monkeypatch):
    monkeypatch.setattr(cs, "get_maas_client", lambda: mock)
    async with session_factory() as db:
        task = (await db.execute(select(AsyncTask).where(AsyncTask.id == task_id))).scalar_one()
        return await cs.structure_task_handler(db, task)


async def test_document_import_full_flow(client, auth_headers, kb_with_user, session_factory, monkeypatch):
    """DOCX上传→提取正文→MaaS结构化→卡片落库（P1-2 验收主路径）。"""
    docx_bytes = _make_docx("遗忘曲线由艾宾浩斯提出，复习间隔应逐步拉长。")
    ticket = await _upload(client, auth_headers, "document", "notes.docx", docx_bytes)

    imp = await client.post(
        "/api/assets/document",
        json={"obs_key": ticket["obs_key"], "filename": "notes.docx"},
        headers=auth_headers,
    )
    assert imp.status_code == 202, imp.text
    data = imp.json()["data"]

    mock = FakeCardMaaS(_card_payload("遗忘曲线"))
    result = await _run_structure_task(session_factory, data["task_id"], mock, monkeypatch)

    assert result["card_count"] == 1
    async with session_factory() as db:
        asset = await db.get(KnowledgeAsset, data["asset_id"])
        assert asset.parse_status == "done"
        assert "艾宾浩斯" in asset.extracted_text  # 提取正文已缓存
        card = (await db.execute(select(KnowledgeCard).where(KnowledgeCard.asset_id == asset.id))).scalar_one()
        assert card.title == "遗忘曲线"


async def test_pdf_import_flow(client, auth_headers, session_factory, monkeypatch):
    pdf_bytes = _make_pdf("The quick brown fox jumps over the lazy dog. " * 3)
    ticket = await _upload(client, auth_headers, "document", "paper.pdf", pdf_bytes)
    imp = await client.post(
        "/api/assets/document", json={"obs_key": ticket["obs_key"], "filename": "paper.pdf"},
        headers=auth_headers,
    )
    assert imp.status_code == 202
    mock = FakeCardMaaS(_card_payload("PDF卡片"))
    result = await _run_structure_task(session_factory, imp.json()["data"]["task_id"], mock, monkeypatch)
    assert result["card_count"] == 1


async def test_image_import_multimodal_path(client, auth_headers, session_factory, monkeypatch):
    """图片导入：MaaS多模态一次调用（OCR+结构化合一，P1-3 锁定路径）。"""
    # 本地无OBS公网URL → mock图片可访问地址
    monkeypatch.setattr(
        "app.infrastructure.obs_client.image_access_url",
        lambda obs_key: f"https://bucket.obs.example.com/{obs_key}",
    )
    ticket = await _upload(client, auth_headers, "image", "photo.jpg", b"\xff\xd8\xff\xe0-fake-jpeg")
    imp = await client.post(
        "/api/assets/image", json={"obs_key": ticket["obs_key"], "filename": "photo.jpg"},
        headers=auth_headers,
    )
    assert imp.status_code == 202
    mock = FakeCardMaaS(_card_payload("图片卡片"))
    result = await _run_structure_task(session_factory, imp.json()["data"]["task_id"], mock, monkeypatch)

    assert result["card_count"] == 1
    assert mock.calls[0].get("multimodal") is True
    content = mock.calls[0]["messages"][1]["content"]
    assert content[0]["type"] == "text" and content[1]["type"] == "image_url"


async def test_multi_card_split(session_factory, monkeypatch):
    """P1-8 长内容拆分：{"cards":[...]} 返回 → 多卡同素材归属，各自首排。"""
    from datetime import datetime, timedelta, timezone

    from app.models import ReviewTask
    from app.services import card_service as csvc

    monkeypatch.setattr(
        "app.infrastructure.obs_client.image_access_url", lambda obs_key: f"https://x/{obs_key}"
    )
    mock = FakeCardMaaS({"cards": [_card_payload("卡片A"), _card_payload("卡片B"), _card_payload("卡片C")]})
    monkeypatch.setattr(csvc, "get_maas_client", lambda: mock)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    asset = KnowledgeAsset(
        user_id="u-split", kb_id=None, type="text", raw_content="长内容" * 100,
        parse_status="parsing", created_at=now,
    )
    task = AsyncTask(user_id="u-split", type="structure", ref_id=asset.id, status="pending", created_at=now)

    async with session_factory() as db:
        db.add(asset)
        await db.flush()
        task.ref_id = asset.id
        db.add(task)
        await db.commit()
        result = await csvc.structure_task_handler(db, task)

    assert result["card_count"] == 3
    async with session_factory() as db:
        cards = (
            await db.execute(select(KnowledgeCard).where(KnowledgeCard.asset_id == asset.id))
        ).scalars().all()
        assert [c.title for c in cards] == ["卡片A", "卡片B", "卡片C"]
        tasks = (
            await db.execute(select(ReviewTask).where(ReviewTask.card_id.in_([c.id for c in cards])))
        ).scalars().all()
        assert len(tasks) == 3  # 每张卡独立首排
        assert all(t.planned_date == datetime.now(timezone.utc).date() + timedelta(days=1) for t in tasks)


async def test_multi_card_invalid_entry_rejects_all(session_factory, monkeypatch):
    """多卡片中任一张不合法 → 整体失败不落库（spec §5.3.3异常2）。"""
    from datetime import datetime, timezone

    from app.models import KnowledgeCard as KC
    from app.services import card_service as csvc
    from app.services.card_service import StructuredSchemaError

    bad = _card_payload("坏卡片")
    bad["key_points"] = ["只有一条"]  # 违反3~10条
    mock = FakeCardMaaS({"cards": [_card_payload("好卡片"), bad]})
    monkeypatch.setattr(csvc, "get_maas_client", lambda: mock)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    asset = KnowledgeAsset(user_id="u-split2", kb_id=None, type="text", raw_content="x", parse_status="parsing", created_at=now)
    task = AsyncTask(user_id="u-split2", type="structure", ref_id=asset.id, status="pending", created_at=now)
    async with session_factory() as db:
        db.add(asset)
        await db.flush()
        task.ref_id = asset.id
        db.add(task)
        await db.commit()
        with pytest.raises(StructuredSchemaError):
            await csvc.structure_task_handler(db, task)

    async with session_factory() as db:
        assert (await db.execute(select(KC).where(KC.asset_id == asset.id))).scalars().all() == []


async def test_upload_validation_and_isolation(client, auth_headers):
    """类型/大小校验 + 文件归属隔离。"""
    # 非法扩展名
    ticket = (await client.get(
        "/api/obs/presign",
        params={"filename": "evil.exe", "content_type": "application/x-msdownload", "kind": "document"},
        headers=auth_headers,
    )).json()["data"]
    upload = await client.post(
        ticket["upload_url"], params={"obs_key": ticket["obs_key"]},
        files={"file": ("evil.exe", b"MZ...")},
        headers=auth_headers,
    )
    assert upload.status_code == 422

    # 图片超10MB
    ticket2 = (await client.get(
        "/api/obs/presign",
        params={"filename": "big.png", "content_type": "image/png", "kind": "image"},
        headers=auth_headers,
    )).json()["data"]
    upload2 = await client.post(
        ticket2["upload_url"], params={"obs_key": ticket2["obs_key"]},
        files={"file": ("big.png", b"\x89PNG" + b"0" * (10 * 1024 * 1024 + 1))},
        headers=auth_headers,
    )
    assert upload2.status_code == 422

    # 他人文件读取404（先造一份别人的文件）
    other_reg = await client.post(
        "/api/auth/register", json={"email": f"obs-{uuid.uuid4().hex[:6]}@t.cn", "password": "Passw0rd123"}
    )
    other_headers = {"Authorization": f"Bearer {other_reg.json()['data']['token']}"}
    oticket = (await client.get(
        "/api/obs/presign",
        params={"filename": "mine.txt", "content_type": "text/plain", "kind": "document"},
        headers=other_headers,
    )).json()["data"]
    await client.post(
        oticket["upload_url"], params={"obs_key": oticket["obs_key"]},
        files={"file": ("mine.txt", "私有内容".encode())},
        headers=other_headers,
    )
    assert (await client.get(f"/api/obs/file/{oticket['obs_key']}", headers=auth_headers)).status_code == 404
    assert (await client.get(f"/api/obs/file/{oticket['obs_key']}", headers=other_headers)).status_code == 200


async def test_document_import_unknown_file_422(client, auth_headers):
    """obs_key 指向不存在的文件 → 422 引导重新上传。"""
    resp = await client.post(
        "/api/assets/document",
        json={"obs_key": f"someone/document/ghost.pdf", "filename": "ghost.pdf"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
