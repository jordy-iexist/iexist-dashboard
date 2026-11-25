"""werkvoorraad: kaarten per klant

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eén kaart per groep punten uit een bron (scan, analyse, Search Console, aanpassingen) of
    # een eigen taak (`manual`). `active_key` = `group_key` zolang de kaart open staat
    # (todo/doing/review) en anders NULL: per groep hooguit één open kaart, terwijl afgeronde en
    # verwijderde kaarten blijven bestaan. De vorm van `items` staat in
    # features/work_queue/services/types.py.
    op.create_table(
        "work_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("group_key", sa.Text(), nullable=True),
        sa.Column("active_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'todo'")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False, server_default=sa.text("'middel'")),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("items", sa.JSON(), nullable=True),
        sa.Column("fingerprint", sa.String(length=40), nullable=True),
        sa.Column("position", sa.Float(), nullable=False),
        sa.Column("assignee_id", sa.String(length=36), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("resolved_by_source", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_by", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("customer_website_id", "source", "active_key", name="uq_work_item_active"),
    )
    op.create_index("ix_work_items_customer_website_id", "work_items", ["customer_website_id"])
    op.create_index("ix_work_items_status", "work_items", ["status"])


def downgrade() -> None:
    op.drop_index("ix_work_items_status", table_name="work_items")
    op.drop_index("ix_work_items_customer_website_id", table_name="work_items")
    op.drop_table("work_items")
