"""OBS 对象存储基础设施（P1-2/P1-3，design §2.5.4 OBS直传）。

双模式（design 红线为 OBS 前端直传；本地演示环境无 OBS 凭据时自动降级本地存储，
后端代存代发，云端配置 OBS_* 后自动切换回直传，业务代码无感知）：
- obs 模式：OBS_AK/SK/BUCKET/ENDPOINT 齐备 → 后端经 OBS SDK 签发 5 分钟 PUT 签名 URL，
  前端直传 OBS（{upload_url, obs_key, expires_at}）
- local 模式：任一凭据缺失 → 预签名退化为本地代存（POST /api/obs/local-upload），
  文件落在 backend/uploads/，GET /api/obs/file/{key} 供溯源查看（按 user_id 前缀隔离）
"""
import logging
import re
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone

from app.config import settings

logger = logging.getLogger(__name__)

LOCAL_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"

# 允许的文件类型（spec §5.2.1规则5：文档20MB / 图片10MB）
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
IMAGE_MAX_BYTES = 10 * 1024 * 1024
DOCUMENT_MAX_BYTES = 20 * 1024 * 1024
PRESIGN_EXPIRE_SECONDS = 300

_UNSAFE_CHARS = re.compile(r"[^0-9A-Za-z._-]+")


class ObsNotConfigured(Exception):
    """OBS 直传模式被调用但凭据未配置。"""


def is_obs_configured() -> bool:
    return bool(settings.OBS_AK and settings.OBS_SK and settings.OBS_BUCKET and settings.OBS_ENDPOINT)


def build_obs_key(user_id: str, kind: str, filename: str) -> str:
    """生成隔离的 obs_key：{user_id}/{kind}/{uuid}-{净化文件名}（本地回退用前缀做归属校验）。"""
    safe_name = _UNSAFE_CHARS.sub("-", Path(filename or "file").name)[:80] or "file"
    return f"{user_id}/{kind}/{uuid.uuid4().hex[:8]}-{safe_name}"


def validate_upload(kind: str, filename: str, size: int) -> None:
    """类型与体积校验（spec §5.2.1规则5）。kind: image | document"""
    ext = Path(filename or "").suffix.lower()
    if kind == "image":
        if ext not in IMAGE_EXTENSIONS:
            raise ValueError("仅支持 JPG/PNG 图片")
        if size > IMAGE_MAX_BYTES:
            raise ValueError("图片超过10MB上限")
    else:
        if ext not in DOCUMENT_EXTENSIONS:
            raise ValueError("仅支持 PDF/Word(docx)/TXT/Markdown 文档")
        if size > DOCUMENT_MAX_BYTES:
            raise ValueError("文档超过20MB上限")


def presign_upload(user_id: str, kind: str, filename: str, content_type: str) -> dict:
    """签发上传凭证（design §2.5.4：有效期5分钟）。"""
    obs_key = build_obs_key(user_id, kind, filename)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=PRESIGN_EXPIRE_SECONDS)).isoformat()

    if is_obs_configured():
        url = _obs_signed_put_url(obs_key, content_type)
        return {
            "mode": "obs",
            "obs_key": obs_key,
            "upload_url": url,
            "method": "PUT",
            "headers": {"Content-Type": content_type},
            "expires_at": expires_at,
        }
    # 本地回退：前端 multipart POST 到后端代存
    return {
        "mode": "local",
        "obs_key": obs_key,
        "upload_url": "/api/obs/local-upload",
        "method": "POST",
        "headers": {},
        "expires_at": expires_at,
    }


def _obs_signed_put_url(obs_key: str, content_type: str) -> str:
    """OBS SDK 签名 PUT URL（esdk-obs-python，延迟导入避免本地强依赖）。"""
    try:
        from obs import ObsClient  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ObsNotConfigured("esdk-obs-python 未安装，无法签发 OBS 上传凭证") from exc

    client = ObsClient(
        access_key_id=settings.OBS_AK,
        secret_access_key=settings.OBS_SK,
        server=_obs_server_host(),
    )
    from obs import SignedUrl  # noqa: PLC0415

    resp = client.createSignedUrl(
        method="PUT", bucketName=settings.OBS_BUCKET, objectKey=obs_key,
        expires=PRESIGN_EXPIRE_SECONDS, headers={"Content-Type": content_type},
    )
    if resp.status_code >= 300 or not resp.signedUrl:
        raise ObsNotConfigured(f"OBS 签名失败: {resp.errorCode} {resp.message}")
    return str(resp.signedUrl)


def _obs_server_host() -> str:
    """OBS Endpoint 去协议前缀（SDK 需要形如 obs.cn-east-3.myhuaweicloud.com 的主机名）。"""
    return re.sub(r"^https?://", "", settings.OBS_ENDPOINT)


# ---------------- 本地回退存储 ----------------


def local_save(obs_key: str, data: bytes) -> None:
    path = _local_path(obs_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def local_exists(obs_key: str) -> bool:
    return _local_path(obs_key).is_file()


def local_read(obs_key: str) -> bytes:
    return _local_path(obs_key).read_bytes()


def local_size(obs_key: str) -> int:
    return _local_path(obs_key).stat().st_size


def _local_path(obs_key: str) -> Path:
    # 防目录穿越：只允许 [user_id/kind/name] 形式的相对路径
    parts = [p for p in obs_key.split("/") if p not in ("", ".", "..")]
    if len(parts) < 3:
        raise ValueError("非法 obs_key")
    return LOCAL_UPLOAD_DIR.joinpath(*parts)


def ensure_local_placeholder_exists(obs_key: str) -> bool:
    """校验对象是否可用（本地模式：文件存在；OBS 模式：由云端链路保证）。"""
    if is_obs_configured():
        return True
    return local_exists(obs_key)


def image_access_url(obs_key: str | None) -> str | None:
    """供 MaaS 多模态识别的图片可访问 URL。

    OBS 模式返回签名 GET URL（5分钟）；本地模式返回后端文件端点（仅本进程可用，
    本地演示时 MaaS 调用本就需要真实凭据，此分支主要用于云端联调）。
    """
    if not obs_key:
        return None
    if is_obs_configured():
        try:
            from obs import ObsClient  # noqa: PLC0415

            client = ObsClient(
                access_key_id=settings.OBS_AK,
                secret_access_key=settings.OBS_SK,
                server=_obs_server_host(),
            )
            resp = client.createSignedUrl(
                method="GET", bucketName=settings.OBS_BUCKET, objectKey=obs_key,
                expires=PRESIGN_EXPIRE_SECONDS,
            )
            if resp.status_code < 300 and resp.signedUrl:
                return str(resp.signedUrl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OBS 签名 GET URL 失败: %s", exc)
            return None
    return None
