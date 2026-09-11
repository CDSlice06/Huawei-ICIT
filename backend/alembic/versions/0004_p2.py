"""P2 迁移：论坛分享表、拼图记录表、卡片语义向量列（tasks.md P2-1/2/3）

Revision ID: 0004_p2
Revises: 0003_review_stats
Create Date: 2026-09-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.models import Base  # noqa: F401

revision: str = "0004_p2"
down_revision: Union[str, None] = "0003_review_stats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy.schema import CreateTable, CreateIndex

    tables = {t.name: t for t in Base.metadata.sorted_tables}
    for name in ("t_shared_knowledge_base", "t_map_puzzle_record"):
        op.execute(str(CreateTable(tables[name]).compile(bind=bind)))
        for idx in tables[name].indexes:
            op.execute(str(CreateIndex(idx).compile(bind=bind)))
    # 卡片语义向量列（P2-3）
    op.add_column("t_knowledge_card", sa.Column("embedding", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("t_knowledge_card", "embedding")
    op.execute("DROP TABLE IF EXISTS `t_map_puzzle_record`")
    op.execute("DROP TABLE IF EXISTS `t_shared_knowledge_base`")
