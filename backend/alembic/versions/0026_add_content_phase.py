"""livegang fase 3: contentpagina's, voorstellen en Monday-groep

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_websites", sa.Column("monday_group_fase3_id", sa.Text(), nullable=True))

    op.create_table(
        "launch_content_pages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "scan_id",
            sa.String(length=36),
            sa.ForeignKey("launch_scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_page_id",
            sa.String(length=36),
            sa.ForeignKey("launch_scan_pages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("page_type", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("headings", sa.JSON(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("first_paragraph", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("images", sa.JSON(), nullable=True),
        sa.Column("links", sa.JSON(), nullable=True),
        sa.Column("signals", sa.JSON(), nullable=True),
        sa.Column("checks", sa.JSON(), nullable=True),
        sa.Column("problem_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("analysis_status", sa.Text(), nullable=False, server_default=sa.text("'none'")),
        sa.Column("analysis_error", sa.Text(), nullable=True),
        sa.Column("focus_keyword", sa.Text(), nullable=True),
        sa.Column("intent", sa.Text(), nullable=True),
        sa.Column("keyword_source", sa.Text(), nullable=True),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_launch_content_pages_scan_id", "launch_content_pages", ["scan_id"])

    op.create_table(
        "launch_content_suggestions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "scan_id",
            sa.String(length=36),
            sa.ForeignKey("launch_scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_page_id",
            sa.String(length=36),
            sa.ForeignKey("launch_content_pages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("current_value", sa.Text(), nullable=True),
        sa.Column("proposed_value", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_launch_content_suggestions_scan_id", "launch_content_suggestions", ["scan_id"])
    op.create_index(
        "ix_launch_content_suggestions_content_page_id",
        "launch_content_suggestions",
        ["content_page_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_launch_content_suggestions_content_page_id", table_name="launch_content_suggestions")
    op.drop_index("ix_launch_content_suggestions_scan_id", table_name="launch_content_suggestions")
    op.drop_table("launch_content_suggestions")
    op.drop_index("ix_launch_content_pages_scan_id", table_name="launch_content_pages")
    op.drop_table("launch_content_pages")
    op.drop_column("customer_websites", "monday_group_fase3_id")
