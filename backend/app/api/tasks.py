"""异步任务路由：轮询 + SSE 状态推送（tasks.md 4.3，design.md §2.2.2.9）。

- GET /api/tasks/{id}：轮询降级通道
- GET /api/tasks/{id}/stream：SSE 主通道（text/event-stream，任务终态后关闭）
仅任务归属者可查询/订阅（user_id校验，spec §5.4.1规则6）。
SSE 为长连接，生成器内使用独立短会话查询（不占用请求级连接）。
"""
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal, get_db
from app.dependencies import get_current_user, get_owned_record
from app.infrastructure import task_runner
from app.models import AsyncTask, User
from app.schemas.response import ok

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _task_payload(task: AsyncTask) -> dict:
    return {
        "task_id": task.id,
        "type": task.type,
        "ref_id": task.ref_id,
        "status": task.status,
        "retry_count": task.retry_count,
        "error": task.error_msg,
    }


@router.get("/{task_id}", response_model=dict)
async def get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询任务状态（SSE断开时的降级轮询通道）。他人任务统一404（不泄露存在性）。"""
    task = await get_owned_record(db, AsyncTask, task_id, user.id)
    return ok(data=_task_payload(task))


@router.get("/{task_id}/stream")
async def stream_task(
    task_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE 订阅任务状态变更；任务终态（done/failed）后关闭连接。他人任务统一404。"""
    task = await get_owned_record(db, AsyncTask, task_id, user.id)

    initial = _task_payload(task)

    async def event_stream():
        yield f"data: {json.dumps(initial, ensure_ascii=False)}\n\n"
        if initial["status"] in ("done", "failed"):
            return
        last_status = initial["status"]
        while True:
            done = await task_runner.wait_task_done(task_id, timeout=30.0)
            # 独立短会话查询最新状态（SSE长连接不占用请求级连接池）
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(AsyncTask).where(AsyncTask.id == task_id))
                fresh = result.scalar_one_or_none()
            if fresh is None:
                return
            if fresh.status != last_status:
                last_status = fresh.status
                yield f"data: {json.dumps(_task_payload(fresh), ensure_ascii=False)}\n\n"
            if fresh.status in ("done", "failed"):
                return
            if not done:
                yield ": keep-alive\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
