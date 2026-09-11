"""t_review_statistics 复习统计表（P1-7，design §2.3.2、spec §6.7）。

统计数据由复习任务完成记录聚合派生（spec §6.7规则1：系统计算，用户不可直接编辑），
本表为聚合结果的持久化落点（submit 后写穿更新，GET 时重算兜底）。
"""
from datetime import datetime

from sqlalchemy import CHAR, INT, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class ReviewStatistics(UuidPkMixin, Base):
    __tablename__ = "t_review_statistics"
    __table_args__ = ()

    user_id: Mapped[str] = mapped_column(
        CHAR(36), ForeignKey("t_user.id"), nullable=False, unique=True, comment="归属用户(一对一)"
    )
    total_reviews: Mapped[int] = mapped_column(INT, nullable=False, default=0, comment="累计复习次数")
    mastered_count: Mapped[int] = mapped_column(INT, nullable=False, default=0, comment="已掌握卡片数(最近自评为记住)")
    consolidating_count: Mapped[int] = mapped_column(INT, nullable=False, default=0, comment="待巩固卡片数(最近自评为模糊/忘记)")
    trend_data: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="按日遗忘趋势[{date,done,remember}]")
    streak_days: Mapped[int] = mapped_column(INT, nullable=False, default=0, comment="连续打卡天数(P2)")
