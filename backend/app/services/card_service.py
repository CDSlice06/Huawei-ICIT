"""知识卡片服务（tasks.md 5.2/5.3，spec §5.3、§5.6.1规则1首排）。"""
import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.algorithms import spaced_repetition
from app.infrastructure import redis_client
from app.infrastructure.maas_client import get_maas_client
from app.infrastructure.prompts import STRUCTURE_SYSTEM_PROMPT, STRUCTURE_USER_TEMPLATE
from app.models import AsyncTask, KnowledgeAsset, KnowledgeCard, ReviewTask

logger = logging.getLogger(__name__)


class StructuredSchemaError(Exception):
    """结构化输出校验失败（不落库残缺卡片，spec §5.3.3异常2）。"""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _validate_card_schema(data: dict) -> dict:
    """校验结构化输出完整性与字段约束（spec §6.3、§5.3.1规则1）。

    标题/摘要/要点/问答四字段必填非空；标签可空（design v1.1 矛盾修复）。
    """
    errors: list[str] = []
    title = (data.get("title") or "").strip()
    summary = (data.get("summary") or "").strip()
    key_points = data.get("key_points") or []
    qa_pairs = data.get("qa_pairs") or []
    tags = data.get("tags") or []

    if not title:
        errors.append("标题缺失")
    elif len(title) > 100:
        errors.append("标题超过100字符")
    if not summary:
        errors.append("摘要缺失")
    elif len(summary) > 300:
        errors.append("摘要超过300字符")
    if not isinstance(key_points, list) or not (3 <= len(key_points) <= 10):
        errors.append("核心要点须为3~10条")
    elif any(not isinstance(p, str) or len(p) > 200 for p in key_points):
        errors.append("要点为空或超过200字符")
    if not isinstance(qa_pairs, list) or len(qa_pairs) < 1:
        errors.append("自测问答至少1组")
    else:
        for qa in qa_pairs:
            if not isinstance(qa, dict) or not qa.get("question") or not qa.get("answer"):
                errors.append("问答对格式不完整")
                break
    if not isinstance(tags, list) or len(tags) > 10:
        errors.append("标签须为数组且不超过10个")

    if errors:
        raise StructuredSchemaError("；".join(errors))

    return {
        "title": title,
        "summary": summary,
        "key_points": [str(p) for p in key_points],
        "qa_pairs": [{"question": str(q["question"]), "answer": str(q["answer"])} for q in qa_pairs],
        "tags": [str(t)[:20] for t in tags],
    }


def validate_card_payloads(raw: dict) -> list[dict]:
    """兼容单卡片与多卡片（P1-8 长内容拆分）两种返回形态，逐卡校验。

    长素材可输出 {"cards": [卡片1, ...]}（1~5张，同素材归属，spec §5.3.1规则6）；
    任何一张不合法整体失败，不落残缺卡片（spec §5.3.3异常2）。
    """
    if isinstance(raw.get("cards"), list):
        cards_data = raw["cards"]
        if not 1 <= len(cards_data) <= 5:
            raise StructuredSchemaError("拆分卡片数量须为1~5张")
        return [_validate_card_schema(card) for card in cards_data]
    return [_validate_card_schema(raw)]


async def structure_task_handler(db: AsyncSession, task: AsyncTask) -> dict:
    """structure 任务真实 handler（tasks.md 5.2；P1-2/3 扩展文档与图片；P1-8 多卡片）。

    - 文本素材：raw_content → MaaS结构化（P0路径）
    - 文档素材（P1-2）：PyMuPDF/docx 提取正文（存 extracted_text）→ 文本路径
    - 图片素材（P1-3）：MaaS 多模态一次调用（OCR+结构化，120s超时）
    - 长内容拆分（P1-8）：模型可返回 {"cards":[...]}，多卡同素材归属，各自首排
    校验失败不落库残缺卡片，素材保留（spec §5.3.3异常2）。
    """
    asset_result = await db.execute(
        select(KnowledgeAsset).where(KnowledgeAsset.id == task.ref_id)
    )
    asset = asset_result.scalar_one_or_none()
    if asset is None:
        raise StructuredSchemaError(f"素材 {task.ref_id} 不存在")

    client = get_maas_client()
    if asset.type == "doc":
        # 文档正文提取（缓存进 extracted_text，重试不重复解析）
        if not asset.extracted_text:
            from app.infrastructure import document_extractor

            asset.extracted_text = document_extractor.extract_document_text(
                asset.obs_key or "", asset.raw_content or "",
                read_bytes=lambda: _read_asset_bytes(asset),
            )
            await db.commit()
        raw = await client.chat_json(_structure_messages(asset.extracted_text))
    elif asset.type == "image":
        from app.infrastructure import obs_client
        from app.infrastructure.prompts import CARD_IMAGE_USER_PROMPT

        image_url = obs_client.image_access_url(asset.obs_key)
        if not image_url:
            raise StructuredSchemaError("图片不可访问（OBS未配置或文件缺失）")
        raw = await client.chat_json(
            [
                {"role": "system", "content": STRUCTURE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": CARD_IMAGE_USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            multimodal=True,
        )
    else:
        content = asset.extracted_text or asset.raw_content or ""
        raw = await client.chat_json(_structure_messages(content))

    cards_data = validate_card_payloads(raw)

    # 素材无归属库时兜底解析默认库（card.kb_id NOT NULL，spec §5.2.1规则6）
    if asset.kb_id:
        target_kb_id = asset.kb_id
    else:
        from app.services import import_service

        target_kb_id = await import_service.resolve_kb_id(db, task.user_id, None)

    cards: list[KnowledgeCard] = []
    for data in cards_data:
        card = KnowledgeCard(
            user_id=task.user_id,
            kb_id=target_kb_id,
            asset_id=asset.id,
            title=data["title"],
            summary=data["summary"],
            key_points=data["key_points"],
            qa_pairs=data["qa_pairs"],
            tags=data["tags"],
            review_interval_days=spaced_repetition.first_interval(),
            review_count=0,
            created_at=_now(),
        )
        db.add(card)
        cards.append(card)
    await db.flush()

    # 首排复习任务：planned_date=创建日+1天（spec §5.6.1规则1，复用8.2排定函数）
    task_date = _today() + timedelta(days=1)
    from app.services import review_service

    for card in cards:
        await review_service.schedule_first_review(db, card)
    asset.parse_status = "done"
    await db.commit()

    # P2-3：写入语义向量（辅助能力，失败不阻断卡片创建；无embedding的卡片不参与语义搜索）
    try:
        for card in cards:
            card.embedding = await client.embed(f"{card.title}\n{card.summary}")
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("卡片语义向量生成失败（卡片已创建）: %s", exc)

    # 失效相关缓存
    if asset.kb_id:
        await redis_client.invalidate_card_list(str(asset.kb_id))
    await redis_client.cache_delete(
        redis_client.KEY_REVIEW_TODAY.format(user_id=task.user_id, date=task_date.isoformat())
    )
    return {"card_ids": [str(c.id) for c in cards], "title": cards[0].title, "card_count": len(cards)}


def _structure_messages(content: str) -> list[dict]:
    from app.infrastructure.prompts import STRUCTURE_SYSTEM_PROMPT, STRUCTURE_USER_TEMPLATE

    return [
        {"role": "system", "content": STRUCTURE_SYSTEM_PROMPT},
        {"role": "user", "content": STRUCTURE_USER_TEMPLATE.format(content=content)},
    ]


def _read_asset_bytes(asset: KnowledgeAsset) -> bytes:
    """读取素材原始字节（本地回退存储；OBS 模式由云端 getObject 扩展点接入）。"""
    from app.infrastructure import obs_client

    if not obs_client.is_obs_configured() and asset.obs_key:
        return obs_client.local_read(asset.obs_key)
    raise StructuredSchemaError("素材文件不可读（OBS未配置且无本地缓存）")


async def list_cards(
    db: AsyncSession, user_id: str, kb_id: str | None, tag: str | None, page: int, size: int
) -> tuple[list[KnowledgeCard], int]:
    """卡片列表分页查询（created_at倒序，spec §5.3）。"""
    from sqlalchemy import func, text as sa_text

    query = select(KnowledgeCard).where(KnowledgeCard.user_id == user_id)
    count_query = (
        select(func.count())
        .select_from(KnowledgeCard)
        .where(KnowledgeCard.user_id == user_id)
    )
    if kb_id:
        query = query.where(KnowledgeCard.kb_id == kb_id)
        count_query = count_query.where(KnowledgeCard.kb_id == kb_id)
    if tag:
        # JSON数组包含查询（MySQL JSON_CONTAINS）
        query = query.where(
            sa_text("JSON_CONTAINS(tags, :tag_json)").bindparams(
                tag_json=json.dumps(tag, ensure_ascii=False)
            )
        )
    query = query.order_by(KnowledgeCard.created_at.desc())
    query = query.offset((page - 1) * size).limit(size)
    result = await db.execute(query)
    cards = list(result.scalars().all())
    total_result = await db.execute(count_query)
    total = int(total_result.scalar_one() or 0)
    return cards, total


async def get_card(db: AsyncSession, card_id: str, user_id: str) -> KnowledgeCard | None:
    result = await db.execute(select(KnowledgeCard).where(KnowledgeCard.id == card_id))
    card = result.scalar_one_or_none()
    if card is None or card.user_id != user_id:
        return None
    return card


async def update_card(
    db: AsyncSession, card: KnowledgeCard, fields: dict
) -> KnowledgeCard:
    """编辑卡片五字段（spec §5.3.1规则3）。"""
    if "title" in fields and fields["title"]:
        if len(fields["title"]) > 100:
            raise ValueError("标题超过100字符")
        card.title = fields["title"]
    if "summary" in fields and fields["summary"]:
        if len(fields["summary"]) > 300:
            raise ValueError("摘要超过300字符")
        card.summary = fields["summary"]
    if "key_points" in fields and fields["key_points"] is not None:
        card.key_points = fields["key_points"]
    if "qa_pairs" in fields and fields["qa_pairs"] is not None:
        card.qa_pairs = fields["qa_pairs"]
    if "tags" in fields and fields["tags"] is not None:
        card.tags = fields["tags"]
    await db.commit()
    await redis_client.invalidate_card_list(str(card.kb_id))
    return card


async def delete_card(db: AsyncSession, card: KnowledgeCard) -> None:
    """删除卡片：级联清理复习任务与导图节点引用（spec §5.3.1规则4）。"""
    # 级联清理复习任务
    tasks = await db.execute(select(ReviewTask).where(ReviewTask.card_id == card.id))
    for rt in tasks.scalars().all():
        await db.delete(rt)
    # 级联清理导图节点引用（置空card_id而非删节点，保持导图结构）
    from app.models import MapNode

    nodes = await db.execute(select(MapNode).where(MapNode.card_id == card.id))
    for node in nodes.scalars().all():
        node.card_id = None
    kb_id = str(card.kb_id)
    await db.delete(card)
    await db.commit()
    await redis_client.invalidate_card_list(kb_id)
    await redis_client.cache_delete(
        redis_client.KEY_REVIEW_TODAY.format(user_id=card.user_id, date=_today().isoformat()),
    )


async def move_card(db: AsyncSession, card: KnowledgeCard, target_kb_id: str) -> None:
    """移动卡片至其他知识库（spec §5.4.1规则2）。源库与目标库列表缓存均需失效。"""
    source_kb_id = str(card.kb_id) if card.kb_id else None
    card.kb_id = target_kb_id
    await db.commit()
    await redis_client.invalidate_card_list(str(target_kb_id))
    if source_kb_id and source_kb_id != str(target_kb_id):
        await redis_client.invalidate_card_list(source_kb_id)


async def restruct_asset(db: AsyncSession, asset_id: str, user_id: str) -> AsyncTask:
    """重新生成：更新素材状态并重建structure任务（spec §5.3.3异常3）。"""
    result = await db.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    asset = result.scalar_one_or_none()
    if asset is None or asset.user_id != user_id:
        raise ValueError("素材不存在")
    asset.parse_status = "parsing"
    task = AsyncTask(
        user_id=user_id,
        type="structure",
        ref_id=asset.id,
        status="pending",
        created_at=_now(),
    )
    db.add(task)
    await db.commit()
    return task