"""add blog share_token

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-03
"""
import secrets

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("blogs", sa.Column("share_token", sa.String(43), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(text("SELECT id FROM blogs")).fetchall()
    for row in rows:
        token = secrets.token_urlsafe(32)
        bind.execute(
            text("UPDATE blogs SET share_token = :token WHERE id = :id"),
            {"token": token, "id": row.id},
        )

    op.alter_column("blogs", "share_token", nullable=False)
    op.create_unique_constraint("uq_blogs_share_token", "blogs", ["share_token"])
    op.create_index("ix_blogs_share_token", "blogs", ["share_token"])


def downgrade() -> None:
    op.drop_index("ix_blogs_share_token", table_name="blogs")
    op.drop_constraint("uq_blogs_share_token", "blogs", type_="unique")
    op.drop_column("blogs", "share_token")
