"""livegang: dagelijkse sitemap-monitor standaard uit, aan na de eerste nulmeting

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nieuwe klanten beginnen met de dagelijkse controle uit; de worker zet hem aan zodra
    # de eerste fase-1-scan (nulmeting) van de klant is voltooid.
    op.alter_column(
        "customer_websites",
        "sitemap_monitor_enabled",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("false"),
    )
    # Bestaande klanten: aan als er al een voltooide nulmeting is, anders uit.
    op.execute(
        """
        UPDATE customer_websites
        SET sitemap_monitor_enabled = EXISTS (
            SELECT 1 FROM launch_scans
            WHERE launch_scans.customer_website_id = customer_websites.id
              AND launch_scans.phase = 1
              AND launch_scans.status = 'completed'
        )
        """
    )


def downgrade() -> None:
    # Alleen de standaardwaarde terug; de schakelaars per klant blijven zoals ze zijn.
    op.alter_column(
        "customer_websites",
        "sitemap_monitor_enabled",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.text("true"),
    )
