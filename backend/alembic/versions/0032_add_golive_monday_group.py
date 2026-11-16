"""livegang: Monday-groep voor de livegangchecklist

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Groep op het klantbord voor de livegangchecklist (livegangscans hebben phase = 5).
    # Leeg voor bestaande borden: de groep wordt aangemaakt bij het eerste gebruik.
    op.add_column(
        "customer_websites", sa.Column("monday_group_fase5_id", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("customer_websites", "monday_group_fase5_id")
