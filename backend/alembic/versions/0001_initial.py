"""P0 八张核心表初始迁移（tasks.md 2.1/2.2）

基于 app.models.Base.metadata 全量建表（t_user/t_knowledge_base/t_knowledge_asset/
t_knowledge_card/t_mind_map/t_map_node/t_review_task/t_async_task），
含 STORED GENERATED 生成列与 FULLTEXT ngram 全文索引（模型定义内声明）。

说明：初始迁移采用 metadata.create_all 保证与模型定义严格一致；
后续增量变更请使用 alembic revision --autogenerate 产出显式 op。

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op

from app.models import Base  # noqa: F401 导入以注册全部表

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # 逐表建表并建索引（排序依赖：外键目标表先建）
    from sqlalchemy.schema import CreateIndex, CreateTable

    order = [
        "t_user",
        "t_knowledge_base",
        "t_knowledge_asset",
        "t_knowledge_card",
        "t_mind_map",
        "t_map_node",
        "t_review_task",
        "t_async_task",
    ]
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    for name in order:
        table = tables[name]
        op.execute(str(CreateTable(table).compile(bind=bind)))
        for idx in table.indexes:
            op.execute(str(CreateIndex(idx).compile(bind=bind)))


def downgrade() -> None:
    # 逆序删表（外键依赖）
    order = [
        "t_async_task",
        "t_review_task",
        "t_map_node",
        "t_mind_map",
        "t_knowledge_card",
        "t_knowledge_asset",
        "t_knowledge_base",
        "t_user",
    ]
    for name in order:
        op.execute(f"DROP TABLE IF EXISTS `{name}`")