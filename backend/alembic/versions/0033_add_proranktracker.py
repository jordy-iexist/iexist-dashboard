"""livegang: ProRankTracker-snapshot (AI-zichtbaarheid) per scan

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Snapshot van een fase 1-, 2- of 4-scan: score, mentions en links per platform en per prompt.
    op.add_column("launch_scans", sa.Column("proranktracker", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("launch_scans", "proranktracker")
