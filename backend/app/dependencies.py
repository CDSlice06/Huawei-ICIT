"""依赖注入：登录态解析与数据隔离辅助（tasks.md 3.3，spec §4.3.2~§4.3.3）。

- get_current_user：Cookie 或 Bearer 双通道解析 → Redis 会话 → 加载用户，失败统一 401
- get_owned_xxx 系列辅助：所有业务查询强制注入 user_id 过滤（用户隔离铁律）
"""
import secrets
from typing import Any

from fastapi import Cookie, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.infrastructure import redis_client
from app.models import User
from app.schemas.response import ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_UNAUTHORIZED, fail


def _extract_bearer(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None


class UnauthorizedError(Exception):
    """未认证（统一401）。"""


class ForbiddenError(Exception):
    """越权访问（统一403）。"""


class NotFoundError(Exception):
    """资源不存在或无权访问（对外统一404，不泄露存在性）。"""


async def get_token(
    mw_token: str | None = Cookie(default=None, alias="mw_token"),
    authorization: str | None = Header(default=None),
) -> str:
    # 显式 Authorization 头优先于环境 Cookie（多账号/测试场景语义正确）
    token = _extract_bearer(authorization) or mw_token
    if not token:
        raise UnauthorizedError()
    return token


async def get_current_user(
    token: str = Depends(get_token),
    db: AsyncSession = Depends(get_db),
) -> User:
    """登录态解析：token → Redis 会话 → 加载用户。任何失败统一 401。"""
    try:
        user_id = await redis_client.session_get(token)
    except Exception as exc:  # noqa: BLE001
        raise UnauthorizedError() from exc
    if not user_id:
        raise UnauthorizedError()
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise UnauthorizedError()
    return user


def owned_or_404(record: Any, user_id: str) -> Any:
    """数据隔离辅助：记录不存在或不属于当前用户 → 统一 404（不泄露存在性，spec §4.3.2）。"""
    if record is None:
        raise NotFoundError()
    if getattr(record, "user_id", None) != user_id:
        raise NotFoundError()
    return record


async def get_owned_record(db: AsyncSession, model, record_id: str, user_id: str) -> Any:
    """按ID查询并强制归属校验（隔离辅助，供各业务模块复用）。"""
    result = await db.execute(select(model).where(model.id == record_id))
    record = result.scalar_one_or_none()
    return owned_or_404(record, user_id)


def constant_time_equals(a: str, b: str) -> bool:
    """常量时间字符串比较（ADMIN_TOKEN 校验用，任务9.3）。"""
    return secrets.compare_digest(a or "", b or "")


# ---------- 统一异常处理器（main.py 注册） ----------


async def unauthorized_handler(request, exc: UnauthorizedError):
    return fail(ERR_UNAUTHORIZED, "未登录或登录态已过期", status_code=401)


async def forbidden_handler(request, exc: ForbiddenError):
    return fail(ERR_FORBIDDEN, "无权访问该资源", status_code=403)


async def not_found_handler(request, exc: NotFoundError):
    return fail(ERR_NOT_FOUND, "资源不存在", status_code=404)
