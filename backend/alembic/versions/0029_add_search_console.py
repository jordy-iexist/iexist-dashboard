"""livegang fase 4: Google Search Console (property per klant, snapshot per scan)

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Handmatig gekozen property, bijv. "sc-domain:example.nl". Leeg = automatisch op domein.
    op.add_column("customer_websites", sa.Column("gsc_property", sa.Text(), nullable=True))
    # Snapshot van een fase 4-scan: prestaties, sitemaps en URL-inspectie.
    op.add_column("launch_scans", sa.Column("search_console", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("launch_scans", "search_console")
    op.drop_column("customer_websites", "gsc_property")
