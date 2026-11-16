"""livegang fase 4: Bing Webmaster (OAuth-koppeling voor de app, snapshot per scan)

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eén rij per externe dienst; de tokens zijn versleuteld (app.core.secrets).
    op.create_table(
        "oauth_connections",
        sa.Column("provider", sa.String(length=50), primary_key=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_by", sa.String(length=36), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    # Snapshot van een fase 4-scan: index, crawlfouten, sitemaps en klikken uit Bing.
    op.add_column("launch_scans", sa.Column("bing_webmaster", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("launch_scans", "bing_webmaster")
    op.drop_table("oauth_connections")
