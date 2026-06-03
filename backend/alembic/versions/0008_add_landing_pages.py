"""add landing pages

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-03
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. landing_page_uploads
    op.create_table(
        "landing_page_uploads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column(
            "skipped_rows",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. landing_page_rows
    op.create_table(
        "landing_page_rows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "upload_id",
            sa.String(36),
            sa.ForeignKey("landing_page_uploads.id"),
            nullable=False,
        ),
        sa.Column("data", sa.JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # 3. landing_pages
    op.create_table(
        "landing_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("jobs.id"),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("meta_title", sa.Text, nullable=True),
        sa.Column("meta_description", sa.Text, nullable=True),
        sa.Column("slug", sa.Text, nullable=True),
        sa.Column("share_token", sa.String(43), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_landing_pages_share_token", "landing_pages", ["share_token"]
    )
    op.create_index("ix_landing_pages_share_token", "landing_pages", ["share_token"])

    # 4. landing_page_generation_settings
    op.create_table(
        "landing_page_generation_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("reasoning_effort", sa.String(10), nullable=True),
        sa.Column("model", sa.String(50), nullable=True),
        sa.Column("max_output_tokens", sa.Integer, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_landing_page_generation_settings_user_id",
        "landing_page_generation_settings",
        ["user_id"],
    )

    # 5. Add landing_page_row_id to jobs
    op.add_column(
        "jobs",
        sa.Column(
            "landing_page_row_id",
            sa.String(36),
            sa.ForeignKey("landing_page_rows.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "landing_page_row_id")

    op.drop_constraint(
        "uq_landing_page_generation_settings_user_id",
        "landing_page_generation_settings",
        type_="unique",
    )
    op.drop_table("landing_page_generation_settings")

    op.drop_index("ix_landing_pages_share_token", table_name="landing_pages")
    op.drop_constraint(
        "uq_landing_pages_share_token", "landing_pages", type_="unique"
    )
    op.drop_table("landing_pages")

    op.drop_table("landing_page_rows")
    op.drop_table("landing_page_uploads")
