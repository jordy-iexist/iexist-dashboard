"""add image generation settings to blog_generation_settings

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blog_generation_settings",
        sa.Column("image_style_instruction", sa.Text(), nullable=True),
    )
    op.add_column(
        "blog_generation_settings",
        sa.Column("image_size", sa.String(20), nullable=True),
    )
    op.add_column(
        "blog_generation_settings",
        sa.Column("image_model", sa.String(50), nullable=True),
    )
    op.add_column(
        "blog_generation_settings",
        sa.Column("image_quality", sa.String(10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blog_generation_settings", "image_quality")
    op.drop_column("blog_generation_settings", "image_model")
    op.drop_column("blog_generation_settings", "image_size")
    op.drop_column("blog_generation_settings", "image_style_instruction")
