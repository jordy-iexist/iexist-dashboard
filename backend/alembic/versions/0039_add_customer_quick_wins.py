"""quick wins per klant: bewaarde Ahrefs-zoekwoorden op positie 4–20 voor het klantdashboard

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eén rij per klant met de laatst opgehaalde stand; `fetched_at` blijft leeg zolang er nog
    # nooit iets is opgehaald, zodat een mislukte eerste poging bij het volgende bezoek opnieuw mag.
    op.create_table(
        "customer_quick_wins",
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("customer_quick_wins")
