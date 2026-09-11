"""OBS 直传路由（P1-2，design §2.5.4）。

- GET /api/obs/presign：签发5分钟上传凭证（OBS签名PUT URL / 本地代存回退）
- POST /api/obs/local-upload：本地回退模式的后端代存端点（multipart）
- GET /api/obs/file/{key}：本地回退模式的文件读取（溯源查看，按user_id前缀隔离）
"""
import logging

from fastapi import APIRouter, Depends, Query, UploadFile
from fastapi.responses import FileResponse

from app.dependencies import get_current_user, NotFoundError
from app.infrastructure import obs_client
from app.logging_config import log_action
from app.models import User
from app.schemas.response import ERR_VALIDATION, fail, ok

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/obs", tags=["obs"])


@router.get("/presign", response_model=dict)
async def presign(
    filename: str = Query(description="原始文件名"),
    content_type: str = Query(default="application/octet-stream"),
    kind: str = Query(default="document", description="image / document"),
    user: User = Depends(get_current_user),
) -> dict:
    """上传凭证签发：OBS直传（design §2.5.4）或本地代存回退。"""
    if kind not in ("image", "document"):
        return fail(ERR_VALIDATION, "kind 仅支持 image/document", status_code=422)
    return ok(data=obs_client.presign_upload(user.id, kind, filename, content_type))


@router.post("/local-upload", response_model=dict)
async def local_upload(
    file: UploadFile,
    obs_key: str = Query(description="presign 返回的 obs_key"),
    user: User = Depends(get_current_user),
) -> dict:
    """本地回退：后端代存文件（云端 OBS 直传时不经过此端点）。"""
    if obs_client.is_obs_configured():
        return fail(ERR_VALIDATION, "已配置OBS直传，请使用签名URL直传OBS", status_code=422)
    if not obs_key.startswith(f"{user.id}/"):
        return fail(40400, "obs_key 与当前用户不匹配", status_code=404)

    kind = obs_key.split("/")[1]
    data = await file.read()
    try:
        obs_client.validate_upload(kind, file.filename or "", len(data))
        obs_client.local_save(obs_key, data)
    except ValueError as exc:
        return fail(ERR_VALIDATION, str(exc), status_code=422)
    log_action(logger, "obs:local_upload", user_id=user.id, key=obs_key, size=len(data))
    return ok(data={"obs_key": obs_key, "size": len(data)}, message="上传成功")


@router.get("/file/{key:path}", response_class=FileResponse)
async def get_file(
    key: str,
    user: User = Depends(get_current_user),
):
    """本地回退文件读取（错题原图/素材溯源）。他人文件统一404。"""
    if obs_client.is_obs_configured():
        return fail(ERR_VALIDATION, "OBS模式下请使用OBS访问地址", status_code=422)
    if not key.startswith(f"{user.id}/"):
        raise NotFoundError()
    if not obs_client.local_exists(key):
        raise NotFoundError()
    return FileResponse(obs_client._local_path(key))


@router.get("/local-file-url")
async def local_file_url(
    key: str = Query(description="obs_key"),
    user: User = Depends(get_current_user),
) -> dict:
    """前端取本地文件访问URL（img src 用，携带鉴权会话）。"""
    if not key.startswith(f"{user.id}/"):
        return fail(40400, "文件不存在", status_code=404)
    return ok(data={"url": f"/api/obs/file/{key}"})
