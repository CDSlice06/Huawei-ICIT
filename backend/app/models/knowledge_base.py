"""t_knowledge_base 知识库表（design.md §2.3.2、spec.md §6.6）。"""
from datetime import datetime

from sqlalchemy import CHAR, DATETIME, VARCHAR, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class KnowledgeBase(UuidPkMixin, Base):
    __tablename__ = "t_knowledge_base"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="UK_user_name"),
        Index("IDX_kb_user_id", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_user.id"), nullable=False, comment="归属用户")
    name: Mapped[str] = mapped_column(VARCHAR(50), nullable=False, comment="知识库名称，同用户下不重名")
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="创建时间")