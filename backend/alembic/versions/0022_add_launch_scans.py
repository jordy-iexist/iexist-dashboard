"""add launch checklist scans (fase 1: nulmeting & AI scan)

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "launch_scans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("discovery_source", sa.Text(), nullable=True),
        sa.Column("total_urls", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("inventoried_urls", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_urls", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_pages", sa.Integer(), nullable=False, server_default=sa.text("500")),
        sa.Column("vitals_max_pages", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("vitals_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("vitals_measured", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ai_checks", sa.JSON(), nullable=True),
        sa.Column("summary_stats", sa.JSON(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("agent_trace", sa.JSON(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        *_timestamps(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_launch_scans_customer_website_id", "launch_scans", ["customer_website_id"]
    )

    op.create_table(
        "launch_scan_pages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "scan_id",
            sa.String(length=36),
            sa.ForeignKey("launch_scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("in_sitemap", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("redirect_chain", sa.JSON(), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("http_version", sa.Text(), nullable=True),
        sa.Column("indexable", sa.Boolean(), nullable=True),
        sa.Column("indexability_reason", sa.Text(), nullable=True),
        sa.Column("meta_robots", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("title_length", sa.Integer(), nullable=True),
        sa.Column("meta_description", sa.Text(), nullable=True),
        sa.Column("meta_description_length", sa.Integer(), nullable=True),
        sa.Column("h1", sa.JSON(), nullable=True),
        sa.Column("h1_count", sa.Integer(), nullable=True),
        sa.Column("h2", sa.JSON(), nullable=True),
        sa.Column("canonical", sa.Text(), nullable=True),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("lang", sa.Text(), nullable=True),
        sa.Column("hreflang", sa.JSON(), nullable=True),
        sa.Column("internal_links", sa.Integer(), nullable=True),
        sa.Column("external_links", sa.Integer(), nullable=True),
        sa.Column("broken_links", sa.JSON(), nullable=True),
        sa.Column("images_total", sa.Integer(), nullable=True),
        sa.Column("images_missing_alt", sa.Integer(), nullable=True),
        sa.Column("schema_types", sa.JSON(), nullable=True),
        sa.Column("open_graph", sa.JSON(), nullable=True),
        sa.Column("cwv", sa.JSON(), nullable=True),
        sa.Column("cwv_status", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_launch_scan_pages_scan_id", "launch_scan_pages", ["scan_id"])

    op.create_table(
        "launch_scan_issues",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "scan_id",
            sa.String(length=36),
            sa.ForeignKey("launch_scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            sa.String(length=36),
            sa.ForeignKey("launch_scan_pages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("issue_type", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("external_provider", sa.Text(), nullable=True),
        sa.Column("external_item_id", sa.Text(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_launch_scan_issues_scan_id", "launch_scan_issues", ["scan_id"])
    op.create_index("ix_launch_scan_issues_page_id", "launch_scan_issues", ["page_id"])
    op.create_index(
        "ix_launch_scan_issues_issue_type", "launch_scan_issues", ["issue_type"]
    )


def downgrade() -> None:
    op.drop_table("launch_scan_issues")
    op.drop_table("launch_scan_pages")
    op.drop_table("launch_scans")
