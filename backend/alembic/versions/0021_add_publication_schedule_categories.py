"""add scheduled_at and wp_category_ids to blog_publications

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blog_publications",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "blog_publications",
        sa.Column("wp_category_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blog_publications", "wp_category_ids")
    op.drop_column("blog_publications", "scheduled_at")
