"""drop is_active from customer_websites

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-13
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("customer_websites", "is_active")


def downgrade() -> None:
    op.add_column(
        "customer_websites",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
