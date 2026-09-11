"""认证服务（tasks.md 3.1/3.2，spec §5.1.1）。

- bcrypt 加盐哈希（禁止自写MD5，design.md §2.4.5）
- opaque 随机 token（禁止JWT）+ Redis 会话 TTL≥24h
- 注册事务内预建"默认知识库"（design.md v1.1 评审修订）
- 登录失败统一文案防枚举（spec §5.1.3异常2）
"""
import secrets
from datetime import datetime, timezone

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.infrastructure import redis_client
from app.models import KnowledgeBase, User

DEFAULT_KB_NAME = "默认知识库"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _gen_token() -> str:
    return secrets.token_urlsafe(32)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def create_default_kb(db: AsyncSession, user_id: str) -> None:
    """注册时预建默认知识库（kb_id可选缺省目标，保持一键导入零配置）。"""
    db.add(KnowledgeBase(user_id=user_id, name=DEFAULT_KB_NAME, created_at=_now()))


async def register(db: AsyncSession, email: str, password: str) -> tuple[User, str]:
    """注册：校验重复→bcrypt落库→预建默认库→写会话。返回 (user, token)。"""
    existing = await get_user_by_email(db, email)
    if existing is not None:
        raise EmailAlreadyExists()

    user = User(email=email, password_hash=hash_password(password), is_demo=0, created_at=_now())
    db.add(user)
    await db.flush()
    await create_default_kb(db, user.id)
    await db.commit()

    token = _gen_token()
    await redis_client.session_set(token, user.id, settings.session_ttl_seconds)
    return user, token


async def login(db: AsyncSession, email: str, password: str) -> tuple[User, str]:
    """登录：统一失败文案防枚举；成功写会话。返回 (user, token)。"""
    user = await get_user_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentials()

    token = _gen_token()
    await redis_client.session_set(token, user.id, settings.session_ttl_seconds)
    return user, token


async def logout(token: str) -> None:
    await redis_client.session_delete(token)


class EmailAlreadyExists(Exception):
    """邮箱已注册（spec §5.1.1规则3）。"""


class InvalidCredentials(Exception):
    """登录凭据错误（统一文案，防枚举）。"""