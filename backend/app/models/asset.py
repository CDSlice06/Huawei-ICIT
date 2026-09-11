"""t_knowledge_asset 知识素材表（design.md §2.3.2、spec.md §6.2）。

kb_id 可选（spec §6.2规则8调整为可选、缺省默认库，design.md v1.1评审修订）。
extracted_text 建 ngram 全文索引（任务2.2，支撑 §5.4.1规则4 素材搜索维度）。
"""
from datetime import datetime

from sqlalchemy import CHAR, DATETIME, Enum, TEXT, VARCHAR, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class KnowledgeAsset(UuidPkMixin, Base):
    __tablename__ = "t_knowledge_asset"
    __table_args__ = (
        Index("IDX_asset_user_id", "user_id"),
        Index("IDX_asset_kb_id", "kb_id"),
        Index("IDX_asset_parse_status", "parse_status"),
        Index("FTS_asset_extracted", "extracted_text", mysql_prefix="FULLTEXT", mysql_with_parser="ngram"),
    )

    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_user.id"), nullable=False, comment="归属用户")
    kb_id: Mapped[str | None] = mapped_column(
        CHAR(36), ForeignKey("t_knowledge_base.id"), nullable=True, comment="关联知识库(可选，缺省默认库)"
    )
    type: Mapped[str] = mapped_column(Enum("text", "doc", "image"), nullable=False, comment="素材类型")
    raw_content: Mapped[str | None] = mapped_column(TEXT, nullable=True, comment="文本原文")
    obs_key: Mapped[str | None] = mapped_column(VARCHAR(512), nullable=True, comment="OBS对象路径(文档/图片)")
    extracted_text: Mapped[str | None] = mapped_column(TEXT, nullable=True, comment="提取文本(OCR/正文提取)")
    parse_status: Mapped[str] = mapped_column(
        Enum("parsing", "done", "failed"), nullable=False, default="parsing", comment="解析状态"
    )
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="创建时间")
