"""maandrapport per klant

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eén rapport per klant per kalendermaand ("YYYY-MM"). De vorm van `data`, `report`, `manual`
    # en `ai_usage` staat in features/monthly_report/schemas.py. `draft` = rij met alleen
    # handmatige cijfers (nog geen run).
    op.create_table(
        "monthly_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("manual", sa.JSON(), nullable=True),
        sa.Column("ai_usage", sa.JSON(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("customer_website_id", "month", name="uq_monthly_reports_customer_month"),
    )


def downgrade() -> None:
    op.drop_table("monthly_reports")
