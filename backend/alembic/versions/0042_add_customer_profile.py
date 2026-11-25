"""klantprofiel per klant (bedrijf, diensten en prijzen, USP's, bewijs, regels voor AI-content)

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-25
"""
import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eén JSON-kolom; de vorm en het opschonen staan in features/customers/profile.py. Leeg bij
    # bestaande klanten: `parse_profile` maakt daar een leeg profiel van.
    op.add_column("customer_websites", sa.Column("profile", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("customer_websites", "profile")
