"""add published_at to blogs

Revision ID: 0001
Revises:
Create Date: 2026-03-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = "0000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blogs",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blogs", "published_at")
