"""add profile fields to customer_websites

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_websites",
        sa.Column("seo_customer_since", sa.Date(), nullable=True),
    )
    op.add_column(
        "customer_websites",
        sa.Column("seo_goals", sa.Text(), nullable=True),
    )
    op.add_column(
        "customer_websites",
        sa.Column("industry", sa.Text(), nullable=True),
    )
    op.add_column(
        "customer_websites",
        sa.Column("target_blogs_per_month", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer_websites", "target_blogs_per_month")
    op.drop_column("customer_websites", "industry")
    op.drop_column("customer_websites", "seo_goals")
    op.drop_column("customer_websites", "seo_customer_since")
