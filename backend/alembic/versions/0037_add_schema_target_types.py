"""livegang: eigen keuze van schema-types per pagina ("Maak schema")

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Lijst met schema.org-typenamen die "Maak schema" voor deze pagina maakt; NULL = automatisch op paginatype.
    op.add_column("launch_scan_pages", sa.Column("schema_target_types", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("launch_scan_pages", "schema_target_types")
