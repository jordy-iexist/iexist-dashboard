"""add customer_website_id to blogs and landing_pages

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blogs",
        sa.Column("customer_website_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_blogs_customer_website_id",
        "blogs",
        "customer_websites",
        ["customer_website_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_blogs_customer_website_id", "blogs", ["customer_website_id"]
    )

    op.add_column(
        "landing_pages",
        sa.Column("customer_website_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_landing_pages_customer_website_id",
        "landing_pages",
        "customer_websites",
        ["customer_website_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_landing_pages_customer_website_id",
        "landing_pages",
        ["customer_website_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_landing_pages_customer_website_id", "landing_pages")
    op.drop_constraint(
        "fk_landing_pages_customer_website_id", "landing_pages", type_="foreignkey"
    )
    op.drop_column("landing_pages", "customer_website_id")

    op.drop_index("ix_blogs_customer_website_id", "blogs")
    op.drop_constraint("fk_blogs_customer_website_id", "blogs", type_="foreignkey")
    op.drop_column("blogs", "customer_website_id")
