"""zoekwoorden: concurrentenoverzicht per klant

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eén rij per klant voor het scherm Zoekwoorden › Concurrenten. De vorm van `raw`, `data`
    # en `overrides` staat in features/keywords/schemas.py.
    op.create_table(
        "customer_competitor_overviews",
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'idle'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("target", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("overrides", sa.JSON(), nullable=True),
        sa.Column("overrides_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ahrefs_units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ai_usage", sa.JSON(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("customer_competitor_overviews")
