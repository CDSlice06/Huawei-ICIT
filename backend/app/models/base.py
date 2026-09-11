"""公共模型基类：UUID 主键（CHAR(36)，design.md §2.11.3）。"""
import uuid

from sqlalchemy import CHAR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def gen_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class UuidPkMixin:
    id: Mapped[str] = mapped_column(CHAR(36), primary_key=True, default=gen_uuid)