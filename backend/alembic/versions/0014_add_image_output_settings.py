"""add image output format/compression to blog_generation_settings

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blog_generation_settings",
        sa.Column("image_output_format", sa.String(10), nullable=True),
    )
    op.add_column(
        "blog_generation_settings",
        sa.Column("image_output_compression", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blog_generation_settings", "image_output_compression")
    op.drop_column("blog_generation_settings", "image_output_format")
