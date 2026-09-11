"""P1 错题本两表迁移（tasks.md 1.1a，spec §5.8/§6.9~§6.10）

建表 t_mistake_entry（含 tags_text 生成列与 FTS ngram 全文索引）与
t_mistake_quiz_record（测验记录/中断恢复）。模式同 0001：metadata 编译保证与模型一致。

Revision ID: 0002_mistake
Revises: 0001_initial
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op

from app.models import Base  # noqa: F401 导入以注册全部表

revision: str = "0002_mistake"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    from sqlalchemy.schema import CreateIndex, CreateTable

    order = [
        "t_mistake_entry",
        "t_mistake_quiz_record",
    ]
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    for name in order:
        table = tables[name]
        op.execute(str(CreateTable(table).compile(bind=bind)))
        for idx in table.indexes:
            op.execute(str(CreateIndex(idx).compile(bind=bind)))


def downgrade() -> None:
    for name in ("t_mistake_quiz_record", "t_mistake_entry"):
        op.execute(f"DROP TABLE IF EXISTS `{name}`")
