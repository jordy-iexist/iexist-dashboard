"""initial schema

Revision ID: 0000
Revises:
Create Date: 2026-05-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0000"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
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
        "auth_refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "csv_uploads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("template", sa.Text, nullable=False),
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
    )

    op.create_table(
        "csv_rows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "upload_id",
            sa.String(36),
            sa.ForeignKey("csv_uploads.id"),
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

    # jobs created without blog_id FK to avoid circular dependency with blogs
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "row_id",
            sa.String(36),
            sa.ForeignKey("csv_rows.id"),
            nullable=True,
        ),
        sa.Column("blog_id", sa.String(36), nullable=True),
        sa.Column(
            "job_type",
            sa.Text,
            nullable=False,
            server_default=sa.text("'blog_generation'"),
        ),
        sa.Column(
            "status", sa.Text, nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "blogs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "job_id", sa.String(36), sa.ForeignKey("jobs.id"), nullable=False
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Now add FK from jobs.blog_id -> blogs.id
    op.create_foreign_key(
        "fk_jobs_blog_id",
        "jobs",
        "blogs",
        ["blog_id"],
        ["id"],
    )

    op.create_table(
        "wordpress_sites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("base_url", sa.Text, nullable=False),
        sa.Column("wp_login", sa.Text, nullable=False),
        sa.Column("app_password_encrypted", sa.Text, nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
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
        "blog_publications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "blog_id", sa.String(36), sa.ForeignKey("blogs.id"), nullable=False
        ),
        sa.Column(
            "wordpress_site_id",
            sa.String(36),
            sa.ForeignKey("wordpress_sites.id"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.Text, nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column("wp_post_id", sa.Text, nullable=True),
        sa.Column("wp_post_url", sa.Text, nullable=True),
        sa.Column("wp_media_id", sa.Text, nullable=True),
        sa.Column("blog_image_id", sa.String(36), nullable=True),
        sa.Column(
            "wp_status", sa.Text, nullable=False, server_default=sa.text("'draft'")
        ),
        sa.Column("error_code", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("warning_code", sa.Text, nullable=True),
        sa.Column("warning_message", sa.Text, nullable=True),
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
        sa.UniqueConstraint(
            "blog_id", "wordpress_site_id", name="uq_blog_publications_blog_site"
        ),
    )

    op.create_table(
        "blog_images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "blog_id", sa.String(36), sa.ForeignKey("blogs.id"), nullable=False
        ),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("mime_type", sa.Text, nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=False),
        sa.Column("width", sa.Integer, nullable=True),
        sa.Column("height", sa.Integer, nullable=True),
        sa.Column(
            "is_primary",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("generation_prompt", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
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
        "customer_websites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("base_url", sa.Text, nullable=False),
        sa.Column("domain", sa.Text, nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
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
        "website_keywords",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "website_id",
            sa.String(36),
            sa.ForeignKey("customer_websites.id"),
            nullable=False,
        ),
        sa.Column("keyword", sa.Text, nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
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
        sa.UniqueConstraint(
            "website_id", "keyword", name="uq_website_keywords_website_keyword"
        ),
    )

    op.create_table(
        "serp_scans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "website_id",
            sa.String(36),
            sa.ForeignKey("customer_websites.id"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.Text, nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column(
            "market",
            sa.Text,
            nullable=False,
            server_default=sa.text("'google_nl_desktop'"),
        ),
        sa.Column(
            "total_keywords",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "processed_keywords",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "failed_keywords",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "max_requests_per_scan",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'25'"),
        ),
        sa.Column(
            "skipped_due_to_limit",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "truncated_by_limit",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
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
    )

    op.create_table(
        "serp_scan_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "scan_id",
            sa.String(36),
            sa.ForeignKey("serp_scans.id"),
            nullable=False,
        ),
        sa.Column("website_id", sa.String(36), nullable=False),
        sa.Column(
            "keyword_id",
            sa.String(36),
            sa.ForeignKey("website_keywords.id"),
            nullable=False,
        ),
        sa.Column("keyword", sa.Text, nullable=False),
        sa.Column("position", sa.Integer, nullable=True),
        sa.Column("result_url", sa.Text, nullable=True),
        sa.Column("matched_host", sa.Text, nullable=True),
        sa.Column(
            "serp_checked_depth",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'100'"),
        ),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "website_meta_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "website_id",
            sa.String(36),
            sa.ForeignKey("customer_websites.id"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.Text, nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("requested_by", sa.String(36), nullable=False),
        sa.Column(
            "source",
            sa.Text,
            nullable=False,
            server_default=sa.text("'sitemap_first'"),
        ),
        sa.Column(
            "total_pages", sa.Integer, nullable=False, server_default=sa.text("'0'")
        ),
        sa.Column(
            "processed_pages",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "failed_pages",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "max_pages_per_run",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'50'"),
        ),
        sa.Column(
            "skipped_due_to_limit",
            sa.Integer,
            nullable=False,
            server_default=sa.text("'0'"),
        ),
        sa.Column(
            "include_paths",
            sa.JSON,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column(
            "exclude_paths",
            sa.JSON,
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
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
    )

    op.create_table(
        "website_meta_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("website_meta_runs.id"),
            nullable=False,
        ),
        sa.Column("website_id", sa.String(36), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("current_title", sa.Text, nullable=True),
        sa.Column("current_description", sa.Text, nullable=True),
        sa.Column("suggested_title", sa.Text, nullable=True),
        sa.Column("suggested_description", sa.Text, nullable=True),
        sa.Column("approved_title", sa.Text, nullable=True),
        sa.Column("approved_description", sa.Text, nullable=True),
        sa.Column(
            "review_status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'pending_review'"),
        ),
        sa.Column("generation_error", sa.Text, nullable=True),
        sa.Column("reviewed_by", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("run_id", "url", name="uq_website_meta_pages_run_url"),
    )


def downgrade() -> None:
    op.drop_table("website_meta_pages")
    op.drop_table("website_meta_runs")
    op.drop_table("serp_scan_results")
    op.drop_table("serp_scans")
    op.drop_table("website_keywords")
    op.drop_table("customer_websites")
    op.drop_table("blog_images")
    op.drop_table("blog_publications")
    op.drop_table("wordpress_sites")
    op.drop_constraint("fk_jobs_blog_id", "jobs", type_="foreignkey")
    op.drop_table("blogs")
    op.drop_table("jobs")
    op.drop_table("csv_rows")
    op.drop_table("csv_uploads")
    op.drop_table("auth_refresh_tokens")
    op.drop_table("users")
