"""add links target and spreadsheet url to customer_websites

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_websites",
        sa.Column("target_links_per_month", sa.Integer(), nullable=True),
    )
    op.add_column(
        "customer_websites",
        sa.Column("spreadsheet_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customer_websites", "spreadsheet_url")
    op.drop_column("customer_websites", "target_links_per_month")
