"""bureau-overzicht: dagelijkse momentopname van de posities per klant

Revision ID: 0045
Revises: 0044
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eén rij per klant met de laatst opgehaalde ProRankTracker-stand (dagelijks om 07:00 en via
    # de knop "Posities vernieuwen"). De vorm van `drops` en de regels staan in
    # features/agency_overview/services/rank_snapshots.py.
    op.create_table(
        "customer_rank_snapshots",
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("keywords", sa.Integer(), nullable=True),
        sa.Column("top10", sa.Integer(), nullable=True),
        sa.Column("top10_month_ago", sa.Integer(), nullable=True),
        sa.Column("drops", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("customer_rank_snapshots")
