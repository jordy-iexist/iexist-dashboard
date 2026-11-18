"""livegang: gegenereerde JSON-LD per pagina ("Maak schema")

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Voorstel voor ontbrekende structured data per pagina: {jsonld, types, placeholders, notes, problems}.
    op.add_column("launch_scan_pages", sa.Column("schema_suggestion", sa.JSON(), nullable=True))
    op.add_column(
        "launch_scan_pages",
        sa.Column("schema_suggestion_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("launch_scan_pages", "schema_suggestion_at")
    op.drop_column("launch_scan_pages", "schema_suggestion")
