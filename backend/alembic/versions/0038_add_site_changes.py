"""aanpassingen per pagina: beslissingen en afhandeling van voorstellen en actiepunten

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eén rij per beslissing (goedgekeurd / afgewezen / doorgevoerd); open punten zonder beslissing
    # hebben geen rij. `source_key` is stabiel over herscans en heranalyses.
    op.create_table(
        "site_changes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_url", sa.Text(), nullable=False),
        sa.Column("url_key", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.JSON(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_value", sa.Text(), nullable=True),
        sa.Column("proposed_value", sa.Text(), nullable=True),
        sa.Column("approved_value", sa.Text(), nullable=True),
        sa.Column("edited", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("ref", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=True),
        sa.Column("item_label", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=True),
        sa.Column("verify_detail", sa.JSON(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_by", sa.String(length=36), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("customer_website_id", "source_key", name="uq_site_change_source"),
    )
    op.create_index("ix_site_changes_customer_website_id", "site_changes", ["customer_website_id"])
    op.create_index("ix_site_changes_url_key", "site_changes", ["url_key"])


def downgrade() -> None:
    op.drop_index("ix_site_changes_url_key", table_name="site_changes")
    op.drop_index("ix_site_changes_customer_website_id", table_name="site_changes")
    op.drop_table("site_changes")
