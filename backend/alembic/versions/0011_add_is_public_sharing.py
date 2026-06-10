"""add is_public to blogs and landing_pages

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blogs",
        sa.Column(
            "is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column(
        "landing_pages",
        sa.Column(
            "is_public", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("landing_pages", "is_public")
    op.drop_column("blogs", "is_public")
