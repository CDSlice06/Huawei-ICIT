"""错题本数据表（P1-1，spec §5.8/§6.9~§6.10、design §2.3.2）。

- t_mistake_entry 错题条目：三核心字段(题目/正确答案/错因解析) + 错因/知识点标签，
  tags_text 为 STORED GENERATED 生成列（同卡片表方案，json_extract 双方言等价）供全文索引
- t_mistake_quiz_record 错题测验记录：题目序列+逐题标记留存，支撑测验中断恢复（§5.8.3异常4）
- 较design表结构的补充列：parse_status/raw_content（解析状态与原文暂存）——
  条目本体即原始载体（无独立素材表），呼应spec §4.2.3不丢数据与§5.8.3异常2"不落残缺条目"
"""
from datetime import datetime

from sqlalchemy import (
    CHAR,
    Computed,
    DATETIME,
    Enum,
    JSON,
    TEXT,
    VARCHAR,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class MistakeEntry(UuidPkMixin, Base):
    __tablename__ = "t_mistake_entry"
    __table_args__ = (
        Index("IDX_mistake_user_id", "user_id"),
        Index("IDX_mistake_user_mastery", "user_id", "mastery"),
        Index("IDX_mistake_user_created", "user_id", "created_at"),
        Index(
            "FTS_mistake_search",
            "question",
            "answer",
            "error_analysis",
            "tags_text",
            mysql_prefix="FULLTEXT",
            mysql_with_parser="ngram",
        ),
    )

    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_user.id"), nullable=False, comment="归属用户(隔离冗余)")
    question: Mapped[str] = mapped_column(VARCHAR(2000), nullable=False, default="", comment="题目内容(§6.9规则3)")
    answer: Mapped[str] = mapped_column(VARCHAR(2000), nullable=False, default="", comment="正确答案(§6.9规则4)")
    error_analysis: Mapped[str] = mapped_column(VARCHAR(2000), nullable=False, default="", comment="错误原因解析(§6.9规则5)")
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="错因/知识点标签(合计≤10个,每个≤20字符)")
    tags_text: Mapped[str | None] = mapped_column(
        VARCHAR(500), Computed("json_extract(tags, '$')", persisted=True), nullable=True, comment="生成列：仅供全文索引"
    )
    source_type: Mapped[str] = mapped_column(
        Enum("image", "text"), nullable=False, comment="录入来源(§6.9规则7,创建后不可变更)"
    )
    obs_key: Mapped[str | None] = mapped_column(VARCHAR(512), nullable=True, comment="原图OBS引用(图片类必填,溯源查看)")
    kb_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("t_knowledge_base.id"), nullable=True, comment="关联知识库(可选)")
    card_id: Mapped[str | None] = mapped_column(CHAR(36), ForeignKey("t_knowledge_card.id"), nullable=True, comment="关联卡片(可选)")
    mastery: Mapped[str] = mapped_column(
        Enum("unmastered", "mastered"), nullable=False, default="unmastered", comment="掌握状态(§6.9规则10)"
    )
    parse_status: Mapped[str] = mapped_column(
        Enum("parsing", "done", "failed"), nullable=False, default="done", comment="解析状态(补充列,MaaS解析流转)"
    )
    raw_content: Mapped[str | None] = mapped_column(TEXT, nullable=True, comment="录入原文暂存(文本类解析输入/失败恢复,补充列)")
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="录入时间(按顺序抽取依据,§6.9规则11)")


class MistakeQuizRecord(UuidPkMixin, Base):
    __tablename__ = "t_mistake_quiz_record"
    __table_args__ = (
        Index("IDX_quiz_user_id", "user_id"),
        Index("IDX_quiz_user_status", "user_id", "progress"),
    )

    user_id: Mapped[str] = mapped_column(CHAR(36), ForeignKey("t_user.id"), nullable=False, comment="归属用户")
    strategy: Mapped[str] = mapped_column(
        Enum("sequential", "random"), nullable=False, comment="抽取策略(§6.10规则3)"
    )
    scope: Mapped[dict] = mapped_column(JSON, nullable=False, comment="抽取范围条件(如仅未掌握)")
    entry_ids: Mapped[list] = mapped_column(JSON, nullable=False, comment="题目序列(有序条目ID数组,§6.10规则4)")
    progress: Mapped[str] = mapped_column(
        Enum("in_progress", "done", "abandoned"), nullable=False, default="in_progress", comment="测验进度(§6.10规则5)"
    )
    marks: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="逐题标记结果[{entry_id,mark}](§6.10规则6)")
    started_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="发起时间")
    ended_at: Mapped[datetime | None] = mapped_column(DATETIME, nullable=True, comment="结束时间(完成或放弃)")
