"""livegang: Ahrefs-data per scan en per pagina

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("launch_scans", sa.Column("ahrefs", sa.JSON(), nullable=True))
    op.add_column("launch_scan_pages", sa.Column("org_traffic", sa.Integer(), nullable=True))
    op.add_column("launch_scan_pages", sa.Column("refdomains", sa.Integer(), nullable=True))
    op.add_column("launch_scan_pages", sa.Column("ahrefs", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("launch_scan_pages", "ahrefs")
    op.drop_column("launch_scan_pages", "refdomains")
    op.drop_column("launch_scan_pages", "org_traffic")
    op.drop_column("launch_scans", "ahrefs")
