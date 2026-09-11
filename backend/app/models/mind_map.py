"""t_mind_map 思维导图表 + t_map_node 导图节点表（design.md §2.3.2、spec.md §6.4）。

t_mind_map.kb_id UNIQUE（一库一图）；t_map_node.parent_id 自引用可空（根节点为NULL）；
pos_x/pos_y 拖拽编排后保存，未编排时为 NULL（前端默认树布局）。
"""
from datetime import datetime

from sqlalchemy import CHAR, DATETIME, Enum, FLOAT, VARCHAR, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class MindMap(UuidPkMixin, Base):
    __tablename__ = "t_mind_map"
    __table_args__ = (Index("IDX_map_kb_id", "kb_id", unique=True),)

    kb_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("t_knowledge_base.id"), nullable=False, unique=True, comment="归属知识库(一库一图)"
    )
    version_source: Mapped[str] = mapped_column(
        Enum("auto", "manual"), nullable=False, default="auto", comment="版本来源(自动生成/手动编辑)"
    )
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="创建时间")


class MapNode(UuidPkMixin, Base):
    __tablename__ = "t_map_node"
    __table_args__ = (
        Index("IDX_node_map_id", "map_id"),
        Index("IDX_node_parent_id", "parent_id"),
        Index("IDX_node_card_id", "card_id"),
    )

    map_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_mind_map.id"), nullable=False, comment="归属导图")
    parent_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("t_map_node.id"), nullable=True, comment="父节点(根节点为NULL)"
    )
    title: Mapped[str] = mapped_column(VARCHAR(50), nullable=False, comment="节点标题")
    card_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("t_knowledge_card.id"), nullable=True, comment="关联卡片(仅叶子节点)"
    )
    pos_x: Mapped[float | None] = mapped_column(FLOAT, nullable=True, comment="画布X坐标(拖拽编排后)")
    pos_y: Mapped[float | None] = mapped_column(FLOAT, nullable=True, comment="画布Y坐标(拖拽编排后)")