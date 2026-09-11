"""统一响应格式（design.md §2.2.1：{code, message, data}，code=0 成功）。"""
from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}


def fail(code: int, message: str, data: Any = None, status_code: int | None = None) -> JSONResponse:
    body = {"code": code, "message": message, "data": data}
    return JSONResponse(status_code=status_code or 400, content=body)


# 常用业务错误码
ERR_UNAUTHORIZED = 40100
ERR_FORBIDDEN = 40300
ERR_NOT_FOUND = 40400
ERR_CONFLICT = 40900
ERR_VALIDATION = 42200
ERR_RATE_LIMIT = 42900
ERR_INTERNAL = 50000
ERR_UPSTREAM = 50200