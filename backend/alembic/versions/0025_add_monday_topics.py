"""livegang: Monday-hoofditem per onderwerp (actiepunten als subitems)

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "launch_monday_topics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("item_id", sa.Text(), nullable=False),
        sa.Column("item_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("customer_website_id", "issue_type", name="uq_launch_monday_topic"),
    )
    op.create_index(
        "ix_launch_monday_topics_customer_website_id",
        "launch_monday_topics",
        ["customer_website_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_launch_monday_topics_customer_website_id", table_name="launch_monday_topics")
    op.drop_table("launch_monday_topics")
