"""add customer_sheet_columns and customer_sheet_cells tables

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_sheet_columns",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_customer_sheet_columns_customer_website_id",
        "customer_sheet_columns",
        ["customer_website_id"],
    )

    op.create_table(
        "customer_sheet_cells",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "column_id",
            sa.String(length=36),
            sa.ForeignKey("customer_sheet_columns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "blog_id",
            sa.String(length=36),
            sa.ForeignKey("blogs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "column_id", "blog_id", name="uq_customer_sheet_cells_column_blog"
        ),
    )
    op.create_index(
        "ix_customer_sheet_cells_column_id",
        "customer_sheet_cells",
        ["column_id"],
    )
    op.create_index(
        "ix_customer_sheet_cells_blog_id",
        "customer_sheet_cells",
        ["blog_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_customer_sheet_cells_blog_id", table_name="customer_sheet_cells")
    op.drop_index("ix_customer_sheet_cells_column_id", table_name="customer_sheet_cells")
    op.drop_table("customer_sheet_cells")

    op.drop_index(
        "ix_customer_sheet_columns_customer_website_id",
        table_name="customer_sheet_columns",
    )
    op.drop_table("customer_sheet_columns")
