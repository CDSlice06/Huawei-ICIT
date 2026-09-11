"""t_async_task 异步任务表（design.md §2.3.2、spec.md §5.3.1规则5）。"""
from datetime import datetime

from sqlalchemy import CHAR, DATETIME, Enum, INT, TEXT, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class AsyncTask(UuidPkMixin, Base):
    __tablename__ = "t_async_task"
    __table_args__ = (
        Index("IDX_task_user_id", "user_id"),
        Index("IDX_task_status", "status"),
        Index("IDX_task_ref_id", "ref_id"),
    )

    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_user.id"), nullable=False, comment="归属用户")
    type: Mapped[str] = mapped_column(
        Enum("structure", "ocr", "map_gen", "mistake_parse"), nullable=False, comment="任务类型"
    )
    ref_id: Mapped[str] = mapped_column(CHAR(36), nullable=False, comment="关联业务对象ID(素材/导图等)")
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "done", "failed"), nullable=False, default="pending", comment="任务状态"
    )
    retry_count: Mapped[int] = mapped_column(INT, nullable=False, default=0, comment="重试次数(≤2)")
    error_msg: Mapped[str | None] = mapped_column(TEXT, nullable=True, comment="错误信息")
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="创建时间")