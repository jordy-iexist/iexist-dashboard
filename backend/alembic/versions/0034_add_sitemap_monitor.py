"""livegang: dagelijkse sitemap-monitor en "Maak prompt" per actiepunt

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schakelaar per klant voor de dagelijkse sitemap-monitor; standaard aan.
    op.add_column(
        "customer_websites",
        sa.Column(
            "sitemap_monitor_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    # Groep op het klantbord voor de sitemap-monitor (monitorscans hebben phase = 6).
    # Leeg voor bestaande borden: de groep wordt aangemaakt bij het eerste gebruik.
    op.add_column(
        "customer_websites", sa.Column("monday_group_fase6_id", sa.Text(), nullable=True)
    )

    # Laatst bekende sitemap-stand per klant: {url_key: {url, lastmod}} en recente wijzigingen.
    op.create_table(
        "launch_sitemap_snapshots",
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("entries", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("recent_changes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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

    # Gegenereerde opdracht voor Claude Code per actiepunt ("Maak prompt").
    op.add_column("launch_scan_issues", sa.Column("fix_prompt", sa.Text(), nullable=True))
    op.add_column(
        "launch_scan_issues",
        sa.Column("fix_prompt_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("launch_scan_issues", "fix_prompt_at")
    op.drop_column("launch_scan_issues", "fix_prompt")
    op.drop_table("launch_sitemap_snapshots")
    op.drop_column("customer_websites", "monday_group_fase6_id")
    op.drop_column("customer_websites", "sitemap_monitor_enabled")
