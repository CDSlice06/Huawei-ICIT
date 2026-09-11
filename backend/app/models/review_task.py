"""t_review_task 复习任务表（design.md §2.3.2、spec.md §6.5）。"""
from datetime import date, datetime

from sqlalchemy import CHAR, DATE, DATETIME, Enum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class ReviewTask(UuidPkMixin, Base):
    __tablename__ = "t_review_task"
    __table_args__ = (
        Index("IDX_review_user_id", "user_id"),
        Index("IDX_user_planned", "user_id", "planned_date"),
        Index("IDX_review_card_id", "card_id"),
    )

    card_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_knowledge_card.id"), nullable=False, comment="关联卡片")
    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_user.id"), nullable=False, comment="归属用户(隔离冗余)")
    planned_date: Mapped[date] = mapped_column(DATE, nullable=False, comment="计划复习日期")
    status: Mapped[str] = mapped_column(
        Enum("pending", "done", "postponed"), nullable=False, default="pending", comment="任务状态"
    )
    rating: Mapped[str | None] = mapped_column(
        Enum("forget", "blur", "remember"), nullable=True, comment="掌握度自评"
    )
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME, nullable=True, comment="完成时间")