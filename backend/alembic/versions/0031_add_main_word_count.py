"""livegang fase 1: woorden in de hoofdinhoud per pagina

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Woorden buiten nav/header/footer/aside; NULL als de pagina geen van die elementen
    # heeft (en voor scans van vóór deze migratie).
    op.add_column("launch_scan_pages", sa.Column("main_word_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("launch_scan_pages", "main_word_count")
