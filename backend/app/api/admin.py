"""运维管理路由（tasks.md 9.3，spec §5.1.1规则6）。

POST /api/admin/demo/reset：ADMIN_TOKEN Bearer 保护（独立运维通道，不与用户会话混用），
演示当天评委改乱数据可远程一键恢复。
"""
import logging

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.dependencies import constant_time_equals
from app.logging_config import log_action
from app.schemas.response import ERR_UNAUTHORIZED, fail, ok
from app.services import demo_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def verify_admin_token(
    authorization: str | None = Header(default=None),
) -> None:
    """ADMIN_TOKEN Bearer 校验（常量时间比较，tasks.md 9.3）。"""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    if not settings.ADMIN_TOKEN or not constant_time_equals(token or "", settings.ADMIN_TOKEN):
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="运维令牌无效")


@router.post("/demo/reset", response_model=dict)
async def reset_demo(
    request: Request,
    _: None = Depends(verify_admin_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """远程一键重置演示账号数据（幂等，恢复初始预置状态）。"""
    try:
        stats = await demo_service.reset_demo_account(db)
    except demo_service.DemoAccountNotConfigured as exc:
        return fail(40400, str(exc), status_code=404)
    client_ip = request.client.host if request.client else "unknown"
    log_action(logger, "admin:demo_reset", status="ok", source_ip=client_ip,
               kbs=stats.get("kbs"), cards=stats.get("cards"))
    return ok(data=stats, message="演示账号已重置")