"""认证路由（tasks.md 3.1/3.2，design.md §2.2.2.1）。

会话载体：httpOnly Cookie（同域部署下 EventSource 自动携带，tasks.md 决策记录3）；
同时接受 Authorization: Bearer 双通道便于 curl 测试。
"""
import logging

from fastapi import APIRouter, Cookie, Depends, Header, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.logging_config import log_action
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    PhoneRegisterRequest,
    RegisterRequest,
    SmsCodeRequest,
    UserBrief,
)
from app.schemas.response import ERR_CONFLICT, ERR_UNAUTHORIZED, ERR_VALIDATION, fail, ok
from app.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

TOKEN_COOKIE = "mw_token"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=TOKEN_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=24 * 3600,
    )


def _auth_response(user, token: str) -> dict:
    body = AuthResponse(token=token, user=UserBrief(id=user.id, email=user.email)).model_dump()
    return ok(data=body)


@router.post("/register", response_model=dict)
async def register(
    payload: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """邮箱注册：创建账号+预建默认知识库+自动登录（spec §5.1.1规则1）。"""
    try:
        user, token = await auth_service.register(db, payload.email, payload.password)
    except auth_service.EmailAlreadyExists:
        return fail(ERR_CONFLICT, "该邮箱已注册，请直接登录", status_code=409)
    _set_session_cookie(response, token)
    log_action(logger, "register", user_id=user.id)
    return _auth_response(user, token)


@router.post("/login", response_model=dict)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """登录：凭据校验+写会话；失败统一文案防枚举（spec §5.1.3异常2）。"""
    try:
        user, token = await auth_service.login(db, payload.email, payload.password)
    except auth_service.InvalidCredentials:
        return fail(ERR_UNAUTHORIZED, "邮箱或密码错误", status_code=401)
    _set_session_cookie(response, token)
    log_action(logger, "login", user_id=user.id)
    return _auth_response(user, token)


@router.post("/sms/code", response_model=dict)
async def send_sms_code(payload: SmsCodeRequest) -> dict:
    """发送短信验证码（P2-5，ENABLE_SMS开关保护；console驱动仅日志输出）。"""
    from app.infrastructure import sms as sms_infra

    try:
        await sms_infra.send_code(payload.phone)
    except sms_infra.SmsNotConfigured as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    except sms_infra.SmsSendError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=503)
    return ok(message="验证码已发送")


@router.post("/register/phone", response_model=dict)
async def register_by_phone(
    payload: PhoneRegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """手机号+验证码注册（P2-5）。创建账号时以占位邮箱满足邮箱唯一约束。"""
    from app.infrastructure import sms as sms_infra

    if not await sms_infra.verify_code(payload.phone, payload.code):
        return fail(ERR_VALIDATION, "验证码错误或已过期", status_code=422)
    placeholder_email = f"{payload.phone}@phone.placeholder"
    try:
        user, token = await auth_service.register(db, placeholder_email, payload.password)
    except auth_service.EmailAlreadyExists:
        return fail(ERR_CONFLICT, "该手机号已注册，请直接登录", status_code=409)
    user.phone = payload.phone
    await db.commit()
    _set_session_cookie(response, token)
    log_action(logger, "register_phone", user_id=user.id)
    return _auth_response(user, token)


@router.post("/logout", response_model=dict)
async def logout(
    response: Response,
    mw_token: str | None = Cookie(default=None, alias=TOKEN_COOKIE),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """登出：清除Redis会话+清除Cookie。"""
    # 显式 Authorization 头优先于环境 Cookie（与 get_token 语义一致）
    token = _extract_bearer(authorization) or mw_token
    if token:
        try:
            await auth_service.logout(token)
        except Exception:  # noqa: BLE001 Redis不可用时也完成Cookie清除
            pass
    response.delete_cookie(key=TOKEN_COOKIE, path="/")
    return ok()


@router.get("/me", response_model=dict)
async def me(
    mw_token: str | None = Cookie(default=None, alias=TOKEN_COOKIE),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """当前用户信息。"""
    # 显式 Authorization 头优先于环境 Cookie（与 get_token 语义一致）
    token = _extract_bearer(authorization) or mw_token
    if not token:
        return fail(ERR_UNAUTHORIZED, "未登录", status_code=401)
    try:
        user_id = await auth_service.redis_client.session_get(token)
    except Exception:  # noqa: BLE001
        return fail(ERR_UNAUTHORIZED, "未登录", status_code=401)
    if not user_id:
        return fail(ERR_UNAUTHORIZED, "登录态已过期", status_code=401)
    from sqlalchemy import select

    from app.models import User

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return fail(ERR_UNAUTHORIZED, "用户不存在", status_code=401)
    return ok(data=UserBrief(id=user.id, email=user.email).model_dump())


def _extract_bearer(authorization: str | None) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization[7:]
    return None