"""P1 复习统计表迁移（tasks.md 1.7a，spec §6.7）

Revision ID: 0003_review_stats
Revises: 0002_mistake
Create Date: 2026-09-12
"""

from typing import Sequence, Union

from alembic import op

from app.models import Base  # noqa: F401

revision: str = "0003_review_stats"
down_revision: Union[str, None] = "0002_mistake"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy.schema import CreateTable

    tables = {t.name: t for t in Base.metadata.sorted_tables}
    op.execute(str(CreateTable(tables["t_review_statistics"]).compile(bind=bind)))


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS `t_review_statistics`")
