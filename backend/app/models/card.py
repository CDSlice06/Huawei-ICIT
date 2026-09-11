"""t_knowledge_card 知识卡片表（design.md §2.3.2、spec.md §6.3）。

key_points_text / tags_text 为 STORED GENERATED 生成列（任务2.2）——
MySQL 不支持 JSON 列直接建 FULLTEXT，经生成列中转支撑 ngram 全文检索。
表达式用 json_extract(col,'$')：对 JSON 数组与 JSON_UNQUOTE 输出等价，
且为 MySQL 8 / SQLite 双方言通用（业务测试跑 aiosqlite 兼容层，tasks.md 14.1）。
"""
from datetime import datetime

from sqlalchemy import CHAR, Computed, DATETIME, Enum, INT, JSON, VARCHAR, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class KnowledgeCard(UuidPkMixin, Base):
    __tablename__ = "t_knowledge_card"
    __table_args__ = (
        Index("IDX_card_user_id", "user_id"),
        Index("IDX_card_kb_id", "kb_id"),
        Index("IDX_card_asset_id", "asset_id"),
        Index(
            "FTS_card_search",
            "title",
            "summary",
            "tags_text",
            "key_points_text",
            mysql_prefix="FULLTEXT",
            mysql_with_parser="ngram",
        ),
    )

    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_user.id"), nullable=False, comment="归属用户(隔离冗余)")
    kb_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_knowledge_base.id"), nullable=False, comment="归属知识库")
    asset_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_knowledge_asset.id"), nullable=False, comment="来源素材")
    title: Mapped[str] = mapped_column(VARCHAR(100), nullable=False, comment="标题")
    summary: Mapped[str] = mapped_column(VARCHAR(300), nullable=False, comment="摘要")
    key_points: Mapped[list] = mapped_column(JSON, nullable=False, comment="核心要点(3~10条数组)")
    qa_pairs: Mapped[list] = mapped_column(JSON, nullable=False, comment="自测问答(≥1组数组)")
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="标签(≤10个数组)")
    key_points_text: Mapped[str | None] = mapped_column(
        VARCHAR(4000), Computed("json_extract(key_points, '$')", persisted=True), nullable=True, comment="生成列：仅供全文索引"
    )
    tags_text: Mapped[str | None] = mapped_column(
        VARCHAR(500), Computed("json_extract(tags, '$')", persisted=True), nullable=True, comment="生成列：仅供全文索引"
    )
    review_interval_days: Mapped[int] = mapped_column(INT, nullable=False, default=1, comment="当前复习间隔(天)")
    review_count: Mapped[int] = mapped_column(INT, nullable=False, default=0, comment="累计复习次数")
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="创建时间")