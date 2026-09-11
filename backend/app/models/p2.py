"""P2 数据表：知识分享论坛 + 导图拼图记录（tasks.md P2-1/P2-2，spec §5.7/§6.8、§5.5/§6.11）。"""
from datetime import datetime

from sqlalchemy import CHAR, DATETIME, Enum, JSON, VARCHAR, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class SharedKnowledgeBase(UuidPkMixin, Base):
    """t_shared_knowledge_base 论坛分享记录（spec §6.8）。

    发布快照语义：snapshot_content 为分享时刻的只读副本，与原库解耦（§5.7.1规则2）。
    设计修订：不建UK(user_id, source_kb_id)（会阻止取消后重新分享），
    改普通索引 + 应用层校验同一库仅一条 status=shared 记录（design v1.1 修复③）。
    """
    __tablename__ = "t_shared_knowledge_base"
    __table_args__ = (
        Index("IDX_shared_user_id", "user_id"),
        Index("IDX_shared_status", "status"),
        Index("IDX_shared_source_kb", "source_kb_id"),
    )

    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_user.id"), nullable=False, comment="分享者")
    source_kb_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("t_knowledge_base.id"), nullable=False, comment="来源知识库"
    )
    snapshot_title: Mapped[str] = mapped_column(VARCHAR(50), nullable=False, comment="快照标题")
    snapshot_content: Mapped[dict] = mapped_column(JSON, nullable=False, comment="发布快照(卡片+导图+节点坐标)")
    status: Mapped[str] = mapped_column(
        Enum("shared", "cancelled"), nullable=False, default="shared", comment="分享状态"
    )
    shared_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="分享时间")
    updated_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="快照更新时间")


class MapPuzzleRecord(UuidPkMixin, Base):
    """t_map_puzzle_record 导图拼图自测记录（spec §6.11）。

    固定布局、逐层拼装简化模式（spec §5.5.1备注）：打散快照含答案键（服务端判定），
    中途退出不产生结果记录（progress=in_progress 不写入 result）。
    """
    __tablename__ = "t_map_puzzle_record"
    __table_args__ = (
        Index("IDX_puzzle_user_id", "user_id"),
        Index("IDX_puzzle_kb_id", "kb_id"),
    )

    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_user.id"), nullable=False, comment="归属用户")
    kb_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_knowledge_base.id"), nullable=False, comment="关联知识库")
    map_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_mind_map.id"), nullable=False, comment="关联导图")
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, comment="打散快照(节点列表+父子答案键)")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="拼装结果(正确数/总数,仅已完成)")
    progress: Mapped[str] = mapped_column(
        Enum("in_progress", "done"), nullable=False, default="in_progress", comment="进度(中途退出不写结果)"
    )
    started_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="发起时间")
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME, nullable=True, comment="完成时间")
