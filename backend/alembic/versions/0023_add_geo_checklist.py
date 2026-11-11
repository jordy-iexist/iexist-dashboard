"""livegang fase 2: GEO/SEO-checklist

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fase-2 run = launch_scan met phase=2 die naar de fase-1 scan verwijst.
    op.add_column(
        "launch_scans",
        sa.Column(
            "source_scan_id",
            sa.String(length=36),
            sa.ForeignKey("launch_scans.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("launch_scans", sa.Column("checklist", sa.JSON(), nullable=True))
    op.create_index("ix_launch_scans_source_scan_id", "launch_scans", ["source_scan_id"])

    # Verrijking van fase-1 pagina's door fase 2.
    op.add_column("launch_scan_pages", sa.Column("page_type", sa.Text(), nullable=True))
    op.add_column("launch_scan_pages", sa.Column("page_type_source", sa.Text(), nullable=True))
    op.add_column("launch_scan_pages", sa.Column("jsonld", sa.JSON(), nullable=True))
    op.add_column("launch_scan_pages", sa.Column("click_depth", sa.Integer(), nullable=True))
    op.add_column("launch_scan_pages", sa.Column("inlinks", sa.Integer(), nullable=True))
    op.add_column("launch_scan_pages", sa.Column("outlinks", sa.JSON(), nullable=True))
    op.add_column("launch_scan_pages", sa.Column("signals", sa.JSON(), nullable=True))

    op.add_column(
        "customer_websites", sa.Column("launch_is_webshop", sa.Boolean(), nullable=True)
    )

    op.create_table(
        "launch_checklist_states",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("manual_status", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("customer_website_id", "item_key", name="uq_launch_checklist_state"),
    )
    op.create_index(
        "ix_launch_checklist_states_customer", "launch_checklist_states", ["customer_website_id"]
    )

    op.create_table(
        "launch_page_type_overrides",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("page_type", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("customer_website_id", "path", name="uq_launch_page_type_override"),
    )
    op.create_index(
        "ix_launch_page_type_overrides_customer",
        "launch_page_type_overrides",
        ["customer_website_id"],
    )


def downgrade() -> None:
    op.drop_table("launch_page_type_overrides")
    op.drop_table("launch_checklist_states")
    op.drop_column("customer_websites", "launch_is_webshop")
    for col in ("signals", "outlinks", "inlinks", "click_depth", "jsonld", "page_type_source", "page_type"):
        op.drop_column("launch_scan_pages", col)
    op.drop_index("ix_launch_scans_source_scan_id", table_name="launch_scans")
    op.drop_column("launch_scans", "checklist")
    op.drop_column("launch_scans", "source_scan_id")
