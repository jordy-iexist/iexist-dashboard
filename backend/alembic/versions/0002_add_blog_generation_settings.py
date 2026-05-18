"""add blog_generation_settings table

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "blog_generation_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, unique=True),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("reasoning_effort", sa.String(10), nullable=True),
        sa.Column("model", sa.String(50), nullable=True),
        sa.Column("max_output_tokens", sa.Integer, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("blog_generation_settings")
