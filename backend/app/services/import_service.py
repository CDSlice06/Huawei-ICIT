"""素材导入服务（tasks.md 4.1，spec §5.2.1规则1/5/6）。

- 文本≤5000字符（超限拒绝）；kb_id可选缺省默认库（一键零配置）
- 事务内先建素材（不丢数据）再建异步任务；返回202
- 单用户并发闸门：pending+running 任务数≥2 返回429（design.md §2.1.3.1）
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AsyncTask, KnowledgeAsset, KnowledgeBase


class TextTooLong(Exception):
    """文本超出5000字符（spec §5.2.1规则5）。"""


class GateLimitReached(Exception):
    """单用户进行中任务数达上限（design.md §2.1.3.1 并发闸门）。"""


class KnowledgeBaseNotFound(Exception):
    """目标知识库不存在或无权访问。"""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def resolve_kb_id(db: AsyncSession, user_id: str, kb_id: str | None) -> str | None:
    """解析目标知识库：未指定时查默认知识库；指定时校验归属。"""
    if kb_id:
        from app.dependencies import ForbiddenError, NotFoundError

        result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == user_id)
        )
        kb = result.scalar_one_or_none()
        if kb is None:
            raise KnowledgeBaseNotFound()
        return kb.id
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.user_id == user_id, KnowledgeBase.name == "默认知识库"
        )
    )
    kb = result.scalar_one_or_none()
    if kb is not None:
        return kb.id
    # 默认库缺失（如被删除）时自动重建，保证"一键零配置"导入不中断（spec §5.2.1规则6）
    default_kb = KnowledgeBase(user_id=user_id, name="默认知识库", created_at=_now())
    db.add(default_kb)
    await db.flush()
    return default_kb.id


async def create_text_asset(
    db: AsyncSession, user_id: str, content: str, kb_id: str | None
) -> tuple[KnowledgeAsset, AsyncTask]:
    """创建文本素材+异步结构化任务（素材先于任务落盘，spec §4.2.3）。"""
    if len(content) > settings.TEXT_MAX_CHARS:
        raise TextTooLong()

    resolved_kb = await resolve_kb_id(db, user_id, kb_id)

    asset = KnowledgeAsset(
        user_id=user_id,
        kb_id=resolved_kb,
        type="text",
        raw_content=content,
        parse_status="parsing",
        created_at=_now(),
    )
    db.add(asset)
    await db.flush()

    task = AsyncTask(
        user_id=user_id,
        type="structure",
        ref_id=asset.id,
        status="pending",
        created_at=_now(),
    )
    db.add(task)
    await db.commit()
    return asset, task


async def create_file_asset(
    db: AsyncSession, user_id: str, asset_type: str, obs_key: str, filename: str, kb_id: str | None
) -> tuple[KnowledgeAsset, AsyncTask]:
    """创建文档/图片素材+异步结构化任务（P1-2/P1-3）。

    obs_key 归属校验（{user_id}/ 前缀）；文档将文件名暂存 raw_content 供解析时识别类型。
    """
    from app.infrastructure import obs_client

    if asset_type not in ("doc", "image"):
        raise ValueError("素材类型非法")
    if not obs_key.startswith(f"{user_id}/"):
        raise KnowledgeBaseNotFound()  # 复用"目标不存在"语义 → API层422

    # 上传对象可用性校验（本地回退检查文件存在；OBS模式由直传链路保证）
    if not obs_client.ensure_local_placeholder_exists(obs_key):
        raise FileNotFoundError(obs_key)

    resolved_kb = await resolve_kb_id(db, user_id, kb_id)
    asset = KnowledgeAsset(
        user_id=user_id,
        kb_id=resolved_kb,
        type=asset_type,
        raw_content=filename if asset_type == "doc" else None,
        obs_key=obs_key,
        parse_status="parsing",
        created_at=_now(),
    )
    db.add(asset)
    await db.flush()
    task = AsyncTask(
        user_id=user_id,
        type="structure",
        ref_id=asset.id,
        status="pending",
        created_at=_now(),
    )
    db.add(task)
    await db.commit()
    return asset, task


class AssetNotFound(Exception):
    """素材不存在。"""


async def get_owned_asset(db: AsyncSession, asset_id: str, user_id: str) -> KnowledgeAsset:
    """按ID查询素材并强制归属校验（spec §4.3.2 数据隔离）。"""
    result = await db.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    asset = result.scalar_one_or_none()
    if asset is None or asset.user_id != user_id:
        raise AssetNotFound()
    return asset


async def delete_asset(db: AsyncSession, asset_id: str, user_id: str) -> None:
    """删除素材记录（关联卡片由卡片删除流程管理，此处仅删素材本体）。"""
    asset = await get_owned_asset(db, asset_id, user_id)
    await db.delete(asset)
    await db.commit()


async def count_running_tasks(db: AsyncSession, user_id: str) -> int:
    """统计该用户 pending+running 任务数。"""
    result = await db.execute(
        select(func.count())
        .select_from(AsyncTask)
        .where(AsyncTask.user_id == user_id, AsyncTask.status.in_(["pending", "running"]))
    )
    return int(result.scalar_one() or 0)


async def check_concurrency_gate(db: AsyncSession, user_id: str) -> None:
    """并发闸门：进行中任务≥上限时拒绝（429）。"""
    count = await count_running_tasks(db, user_id)
    if count >= settings.SINGLE_USER_RUNNING_TASK_LIMIT:
        raise GateLimitReached()