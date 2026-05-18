"""add audit page screenshots

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_pages", sa.Column("screenshots", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("audit_pages", "screenshots")
