"""add website audit tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "website_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("total_pages", sa.Integer, nullable=False, server_default=sa.text("'0'")),
        sa.Column("scanned_pages", sa.Integer, nullable=False, server_default=sa.text("'0'")),
        sa.Column("failed_pages", sa.Integer, nullable=False, server_default=sa.text("'0'")),
        sa.Column("max_pages", sa.Integer, nullable=False, server_default=sa.text("'50'")),
        sa.Column("crawl_source", sa.Text, nullable=True),
        sa.Column("summary", sa.JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
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

    op.create_table(
        "audit_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(36),
            sa.ForeignKey("website_audits.id"),
            nullable=False,
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("typography_data", sa.JSON, nullable=True),
        sa.Column("performance_data", sa.JSON, nullable=True),
        sa.Column("accessibility_data", sa.JSON, nullable=True),
        sa.Column("console_errors", sa.JSON, nullable=True),
        sa.Column("meta_data", sa.JSON, nullable=True),
        sa.Column("links_data", sa.JSON, nullable=True),
        sa.Column("responsive_data", sa.JSON, nullable=True),
        sa.Column("issue_count", sa.Integer, nullable=False, server_default=sa.text("'0'")),
        sa.Column("error_message", sa.Text, nullable=True),
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
        sa.UniqueConstraint("audit_id", "url", name="uq_audit_pages_audit_url"),
    )

    op.create_table(
        "audit_issues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "audit_id",
            sa.String(36),
            sa.ForeignKey("website_audits.id"),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            sa.String(36),
            sa.ForeignKey("audit_pages.id"),
            nullable=True,
        ),
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("selector", sa.Text, nullable=True),
        sa.Column("page_url", sa.Text, nullable=True),
        sa.Column("issue_metadata", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_issues")
    op.drop_table("audit_pages")
    op.drop_table("website_audits")
