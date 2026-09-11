"""结构化日志（design.md §2.9.4：JSON格式，字段 timestamp/user_id/action/duration_ms/status/error）。"""
import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "log_extra", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    # 降低第三方库噪音
    for name in ("uvicorn.access", "uvicorn.error", "aiomysql", "apscheduler"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def log_action(
    logger: logging.Logger,
    action: str,
    *,
    user_id: str | None = None,
    duration_ms: float | None = None,
    status: str = "ok",
    error: str | None = None,
    **kwargs,
) -> None:
    """输出一条结构化操作日志。"""
    extra = {"log_extra": {"action": action, "user_id": user_id, "duration_ms": duration_ms, "status": status, **kwargs}}
    if error:
        logger.error(error, extra=extra)
    else:
        logger.info("", extra=extra)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()