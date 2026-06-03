"""add csv_upload dismissed_at

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("csv_uploads", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("csv_uploads", "dismissed_at")
