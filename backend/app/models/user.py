"""t_user 用户表（design.md §2.3.2、spec.md §6.1）。"""
from datetime import datetime

from sqlalchemy import CHAR, DATETIME, VARCHAR, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UuidPkMixin


class User(UuidPkMixin, Base):
    __tablename__ = "t_user"

    email: Mapped[str] = mapped_column(VARCHAR(255), unique=True, nullable=False, comment="邮箱，全局唯一")
    password_hash: Mapped[str] = mapped_column(VARCHAR(255), nullable=False, comment="bcrypt加盐哈希")
    phone: Mapped[str | None] = mapped_column(VARCHAR(20), unique=True, nullable=True, comment="手机号(P2)")
    is_demo: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False, comment="是否演示账号")
    created_at: Mapped[datetime] = mapped_column(DATETIME, nullable=False, comment="注册时间")