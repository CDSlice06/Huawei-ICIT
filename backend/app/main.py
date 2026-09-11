"""MemWeave（忆织）后端应用入口（design.md §2.7.1）。

FastAPI + Uvicorn；lifespan 中初始化日志、TaskRunner、APScheduler（Redis SETNX 单实例锁）。
业务 handler 注册：structure（5.2）/ map_gen（7.1）。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.dependencies import (
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    forbidden_handler,
    not_found_handler,
    unauthorized_handler,
)
from app.logging_config import setup_logging
from app.schemas.response import ERR_INTERNAL


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    import asyncio

    from app.infrastructure import scheduler, task_runner
    from app.services import card_service, map_service, mistake_service

    # 注册任务处理器（handler注册表机制，tasks.md 4.2/5.2/7.1/P1-1）
    task_runner.register_handler("structure", card_service.structure_task_handler)
    task_runner.register_handler("map_gen", map_service.map_gen_task_handler)
    task_runner.register_handler("mistake_parse", mistake_service.mistake_parse_task_handler)

    loop = asyncio.get_running_loop()
    task_runner.init_runner(loop)
    await scheduler.init_scheduler()
    yield
    await task_runner.shutdown_runner()
    await scheduler.shutdown_scheduler()


app = FastAPI(
    title="MemWeave（忆织）API",
    description="基于华为云MaaS大模型的多源知识编织与抗遗忘记忆系统",
    version="0.1.0",
    lifespan=lifespan,
)

# 统一异常处理（401/403/404 一致格式，design.md §2.2.1）
app.add_exception_handler(UnauthorizedError, unauthorized_handler)
app.add_exception_handler(ForbiddenError, forbidden_handler)
app.add_exception_handler(NotFoundError, not_found_handler)


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception):
    import logging

    logging.getLogger(__name__).error("未处理异常: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": ERR_INTERNAL, "message": "服务内部错误", "data": None},
    )


# 挂载业务路由
from app.api import (  # noqa: E402
    admin,
    assets,
    auth,
    cards,
    knowledge_bases,
    mind_maps,
    mistakes,
    reviews,
    tasks,
)

app.include_router(auth.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(cards.router, prefix="/api")
app.include_router(knowledge_bases.router, prefix="/api")
app.include_router(mind_maps.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(mistakes.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(admin.router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    """健康检查（tasks.md 1.1 验收：返回 code=0）。"""
    return {"code": 0, "message": "ok", "data": {"service": "memweave-backend", "status": "healthy"}}
