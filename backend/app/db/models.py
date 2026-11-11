from __future__ import annotations

import secrets
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import text


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AuthRefreshToken(Base):
    __tablename__ = "auth_refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CsvUpload(Base):
    __tablename__ = "csv_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    skipped_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    rows: Mapped[list["CsvRow"]] = relationship("CsvRow", back_populates="upload")


class CsvRow(Base):
    __tablename__ = "csv_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("csv_uploads.id"), nullable=False
    )
    data: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    upload: Mapped["CsvUpload"] = relationship("CsvUpload", back_populates="rows")
    jobs: Mapped[list["Job"]] = relationship(
        "Job", back_populates="row", foreign_keys="Job.row_id"
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    row_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("csv_rows.id"), nullable=True
    )
    blog_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("blogs.id"), nullable=True
    )
    landing_page_row_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("landing_page_rows.id"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'blog_generation'")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    row: Mapped[Optional["CsvRow"]] = relationship(
        "CsvRow", back_populates="jobs", foreign_keys=[row_id]
    )
    blog: Mapped[Optional["Blog"]] = relationship(
        "Blog", back_populates="generation_job", foreign_keys=[blog_id]
    )
    landing_page_row: Mapped[Optional["LandingPageRow"]] = relationship(
        "LandingPageRow", back_populates="jobs", foreign_keys=[landing_page_row_id]
    )


class Blog(Base):
    __tablename__ = "blogs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    share_token: Mapped[str] = mapped_column(
        String(43), nullable=False, unique=True, index=True,
        default=lambda: secrets.token_urlsafe(32),
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    customer_website_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    placement_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    generation_job: Mapped[list["Job"]] = relationship(
        "Job", back_populates="blog", foreign_keys="Job.blog_id"
    )
    blog_job: Mapped[Optional["Job"]] = relationship(
        "Job", foreign_keys=[job_id], primaryjoin="Blog.job_id == Job.id"
    )
    images: Mapped[list["BlogImage"]] = relationship("BlogImage", back_populates="blog")
    publications: Mapped[list["BlogPublication"]] = relationship(
        "BlogPublication", back_populates="blog"
    )


class WordPressSite(Base):
    __tablename__ = "wordpress_sites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    wp_login: Mapped[str] = mapped_column(Text, nullable=False)
    app_password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    publications: Mapped[list["BlogPublication"]] = relationship(
        "BlogPublication", back_populates="wordpress_site"
    )


class BlogPublication(Base):
    __tablename__ = "blog_publications"
    __table_args__ = (
        UniqueConstraint(
            "blog_id", "wordpress_site_id", name="uq_blog_publications_blog_site"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    blog_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("blogs.id"), nullable=False
    )
    wordpress_site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("wordpress_sites.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    wp_post_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    wp_post_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    wp_media_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blog_image_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    wp_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'draft'")
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    wp_category_ids: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warning_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warning_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    blog: Mapped["Blog"] = relationship("Blog", back_populates="publications")
    wordpress_site: Mapped["WordPressSite"] = relationship(
        "WordPressSite", back_populates="publications"
    )


class BlogImage(Base):
    __tablename__ = "blog_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    blog_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("blogs.id"), nullable=False
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    generation_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    blog: Mapped["Blog"] = relationship("Blog", back_populates="images")


class CustomerCategory(Base):
    __tablename__ = "customer_categories"
    __table_args__ = (
        UniqueConstraint("name", name="uq_customer_categories_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    customer_websites: Mapped[list["CustomerWebsite"]] = relationship(
        "CustomerWebsite", back_populates="category"
    )


class CustomerWebsite(Base):
    __tablename__ = "customer_websites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    seo_customer_since: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    seo_goals: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("customer_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_blogs_per_month: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    target_links_per_month: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    spreadsheet_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    launch_is_webshop: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    monday_board_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    monday_board_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    monday_group_fase1_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    monday_group_fase2_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    monday_group_fase3_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    category: Mapped[Optional["CustomerCategory"]] = relationship(
        "CustomerCategory", back_populates="customer_websites"
    )
    keywords: Mapped[list["WebsiteKeyword"]] = relationship(
        "WebsiteKeyword", back_populates="website"
    )
    serp_scans: Mapped[list["SerpScan"]] = relationship(
        "SerpScan", back_populates="website"
    )
    meta_runs: Mapped[list["WebsiteMetaRun"]] = relationship(
        "WebsiteMetaRun", back_populates="website"
    )
    sheet_columns: Mapped[list["CustomerSheetColumn"]] = relationship(
        "CustomerSheetColumn", back_populates="customer_website"
    )


class CustomerSheetColumn(Base):
    __tablename__ = "customer_sheet_columns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    customer_website: Mapped["CustomerWebsite"] = relationship(
        "CustomerWebsite", back_populates="sheet_columns"
    )
    cells: Mapped[list["CustomerSheetCell"]] = relationship(
        "CustomerSheetCell", back_populates="column"
    )


class CustomerSheetCell(Base):
    __tablename__ = "customer_sheet_cells"
    __table_args__ = (
        UniqueConstraint(
            "column_id", "blog_id", name="uq_customer_sheet_cells_column_blog"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    column_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_sheet_columns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    blog_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("blogs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    column: Mapped["CustomerSheetColumn"] = relationship(
        "CustomerSheetColumn", back_populates="cells"
    )


class WebsiteKeyword(Base):
    __tablename__ = "website_keywords"
    __table_args__ = (
        UniqueConstraint(
            "website_id", "keyword", name="uq_website_keywords_website_keyword"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    website_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customer_websites.id"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    website: Mapped["CustomerWebsite"] = relationship(
        "CustomerWebsite", back_populates="keywords"
    )
    serp_scan_results: Mapped[list["SerpScanResult"]] = relationship(
        "SerpScanResult", back_populates="keyword"
    )


class SerpScan(Base):
    __tablename__ = "serp_scans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    website_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customer_websites.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    market: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'google_nl_desktop'")
    )
    total_keywords: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    processed_keywords: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    failed_keywords: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    max_requests_per_scan: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'25'")
    )
    skipped_due_to_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    truncated_by_limit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    website: Mapped["CustomerWebsite"] = relationship(
        "CustomerWebsite", back_populates="serp_scans"
    )
    results: Mapped[list["SerpScanResult"]] = relationship(
        "SerpScanResult", back_populates="scan"
    )


class SerpScanResult(Base):
    __tablename__ = "serp_scan_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("serp_scans.id"), nullable=False
    )
    website_id: Mapped[str] = mapped_column(String(36), nullable=False)
    keyword_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("website_keywords.id"), nullable=False
    )
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    result_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    matched_host: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    serp_checked_depth: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'100'")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    scan: Mapped["SerpScan"] = relationship("SerpScan", back_populates="results")
    keyword: Mapped["WebsiteKeyword"] = relationship(  # type: ignore[assignment]
        "WebsiteKeyword", back_populates="serp_scan_results", foreign_keys=[keyword_id]
    )


class WebsiteMetaRun(Base):
    __tablename__ = "website_meta_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    website_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("customer_websites.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'sitemap_first'")
    )
    total_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    processed_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    failed_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    max_pages_per_run: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'50'")
    )
    skipped_due_to_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    include_paths: Mapped[Any] = mapped_column(
        JSON, nullable=False, server_default=text("'[]'")
    )
    exclude_paths: Mapped[Any] = mapped_column(
        JSON, nullable=False, server_default=text("'[]'")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    website: Mapped["CustomerWebsite"] = relationship(
        "CustomerWebsite", back_populates="meta_runs"
    )
    pages: Mapped[list["WebsiteMetaPage"]] = relationship(
        "WebsiteMetaPage", back_populates="run"
    )


class WebsiteMetaPage(Base):
    __tablename__ = "website_meta_pages"
    __table_args__ = (
        UniqueConstraint("run_id", "url", name="uq_website_meta_pages_run_url"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("website_meta_runs.id"), nullable=False
    )
    website_id: Mapped[str] = mapped_column(String(36), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    current_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending_review'")
    )
    generation_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    run: Mapped["WebsiteMetaRun"] = relationship(
        "WebsiteMetaRun", back_populates="pages"
    )


class BlogGenerationSettings(Base):
    __tablename__ = "blog_generation_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reasoning_effort: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    image_style_instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_size: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    image_model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    image_quality: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    image_output_format: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    image_output_compression: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LandingPageUpload(Base):
    __tablename__ = "landing_page_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    skipped_rows: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    rows: Mapped[list["LandingPageRow"]] = relationship(
        "LandingPageRow", back_populates="upload"
    )


class LandingPageRow(Base):
    __tablename__ = "landing_page_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("landing_page_uploads.id"), nullable=False
    )
    data: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    upload: Mapped["LandingPageUpload"] = relationship(
        "LandingPageUpload", back_populates="rows"
    )
    jobs: Mapped[list["Job"]] = relationship(
        "Job", back_populates="landing_page_row", foreign_keys="[Job.landing_page_row_id]"
    )


class LandingPage(Base):
    __tablename__ = "landing_pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    slug: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    share_token: Mapped[str] = mapped_column(
        String(43), nullable=False, unique=True, index=True,
        default=lambda: secrets.token_urlsafe(32),
    )
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    customer_website_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    landing_page_job: Mapped[Optional["Job"]] = relationship(
        "Job", foreign_keys=[job_id], primaryjoin="LandingPage.job_id == Job.id"
    )


class LandingPageGenerationSettings(Base):
    __tablename__ = "landing_page_generation_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reasoning_effort: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class UserAISettings(Base):
    __tablename__ = "user_ai_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    encrypted_openai_api_key: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class WebsiteAudit(Base):
    __tablename__ = "website_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    total_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    scanned_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    failed_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    max_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'50'")
    )
    crawl_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Any] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    pages: Mapped[list["AuditPage"]] = relationship("AuditPage", back_populates="audit")
    issues: Mapped[list["AuditIssue"]] = relationship(
        "AuditIssue", back_populates="audit"
    )


class AuditPage(Base):
    __tablename__ = "audit_pages"
    __table_args__ = (
        UniqueConstraint("audit_id", "url", name="uq_audit_pages_audit_url"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("website_audits.id"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    typography_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    performance_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    accessibility_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    console_errors: Mapped[Any] = mapped_column(JSON, nullable=True)
    meta_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    links_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    responsive_data: Mapped[Any] = mapped_column(JSON, nullable=True)
    screenshots: Mapped[Any] = mapped_column(JSON, nullable=True)
    issue_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    audit: Mapped["WebsiteAudit"] = relationship("WebsiteAudit", back_populates="pages")
    issues: Mapped[list["AuditIssue"]] = relationship(
        "AuditIssue", back_populates="page"
    )


class AuditIssue(Base):
    __tablename__ = "audit_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    audit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("website_audits.id"), nullable=False
    )
    page_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("audit_pages.id"), nullable=True
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    selector: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    issue_metadata: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    audit: Mapped["WebsiteAudit"] = relationship(
        "WebsiteAudit", back_populates="issues"
    )
    page: Mapped[Optional["AuditPage"]] = relationship(
        "AuditPage", back_populates="issues"
    )


class LaunchScan(Base):
    __tablename__ = "launch_scans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phase: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    discovery_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    total_urls: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    inventoried_urls: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    failed_urls: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    max_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("500")
    )
    vitals_max_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("100")
    )
    vitals_total: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    vitals_measured: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    source_scan_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("launch_scans.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    checklist: Mapped[Any] = mapped_column(JSON, nullable=True)
    ai_checks: Mapped[Any] = mapped_column(JSON, nullable=True)
    summary_stats: Mapped[Any] = mapped_column(JSON, nullable=True)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent_trace: Mapped[Any] = mapped_column(JSON, nullable=True)
    warnings: Mapped[Any] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LaunchScanPage(Base):
    __tablename__ = "launch_scan_pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("launch_scans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    in_sitemap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    redirect_chain: Mapped[Any] = mapped_column(JSON, nullable=True)
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    http_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    indexable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    indexability_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_robots: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    meta_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_description_length: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    h1: Mapped[Any] = mapped_column(JSON, nullable=True)
    h1_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    h2: Mapped[Any] = mapped_column(JSON, nullable=True)
    canonical: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lang: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hreflang: Mapped[Any] = mapped_column(JSON, nullable=True)
    internal_links: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    external_links: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    broken_links: Mapped[Any] = mapped_column(JSON, nullable=True)
    images_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    images_missing_alt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    schema_types: Mapped[Any] = mapped_column(JSON, nullable=True)
    open_graph: Mapped[Any] = mapped_column(JSON, nullable=True)
    cwv: Mapped[Any] = mapped_column(JSON, nullable=True)
    cwv_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Verrijking door fase 2 (GEO/SEO-checklist)
    page_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_type_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    jsonld: Mapped[Any] = mapped_column(JSON, nullable=True)
    click_depth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    inlinks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    outlinks: Mapped[Any] = mapped_column(JSON, nullable=True)
    signals: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LaunchChecklistState(Base):
    """Handmatige status per checklistpunt per klant (blijft over scans heen)."""

    __tablename__ = "launch_checklist_states"
    __table_args__ = (
        UniqueConstraint("customer_website_id", "item_key", name="uq_launch_checklist_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_key: Mapped[str] = mapped_column(Text, nullable=False)
    manual_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    external_provider: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_item_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pushed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LaunchPageTypeOverride(Base):
    """Handmatige correctie van het paginatype, per klant en pad."""

    __tablename__ = "launch_page_type_overrides"
    __table_args__ = (
        UniqueConstraint("customer_website_id", "path", name="uq_launch_page_type_override"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    path: Mapped[str] = mapped_column(Text, nullable=False)
    page_type: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LaunchMondayTopic(Base):
    """Monday-hoofditem per klant en onderwerp (issue_type).

    Fase-1 actiepunten per pagina worden subitems van dit hoofditem, zodat het
    bord op onderwerp gegroepeerd is. Blijft over scans heen bestaan.
    """

    __tablename__ = "launch_monday_topics"
    __table_args__ = (
        UniqueConstraint("customer_website_id", "issue_type", name="uq_launch_monday_topic"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issue_type: Mapped[str] = mapped_column(Text, nullable=False)
    item_id: Mapped[str] = mapped_column(Text, nullable=False)
    item_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LaunchScanIssue(Base):
    __tablename__ = "launch_scan_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("launch_scans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("launch_scan_pages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    issue_type: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[Any] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'open'")
    )
    external_provider: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_item_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pushed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LaunchContentPage(Base):
    """Pagina-inhoud van een fase-3 scan (eigen rijen, los van fase 1/2)."""

    __tablename__ = "launch_content_pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("launch_scans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_page_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("launch_scan_pages.id", ondelete="SET NULL"),
        nullable=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    page_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    headings: Mapped[Any] = mapped_column(JSON, nullable=True)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    first_paragraph: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    images: Mapped[Any] = mapped_column(JSON, nullable=True)
    links: Mapped[Any] = mapped_column(JSON, nullable=True)
    signals: Mapped[Any] = mapped_column(JSON, nullable=True)
    checks: Mapped[Any] = mapped_column(JSON, nullable=True)
    problem_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    # none | queued | running | done | failed
    analysis_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'none'")
    )
    analysis_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    focus_keyword: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    intent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 'ai' nu; later ook 'ahrefs'.
    keyword_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LaunchContentSuggestion(Base):
    """Concreet verbetervoorstel van een fase-3 agent.

    `content_page_id` leeg = voorstel op siteniveau (contentgap).
    """

    __tablename__ = "launch_content_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("launch_scans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
    )
    content_page_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("launch_content_pages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    item_key: Mapped[str] = mapped_column(Text, nullable=False)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proposed_value: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    details: Mapped[Any] = mapped_column(JSON, nullable=True)
    # open | overgenomen | afgewezen
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'open'")
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


__all__ = [
    "Base",
    "User",
    "AuthRefreshToken",
    "CsvUpload",
    "CsvRow",
    "Job",
    "Blog",
    "WordPressSite",
    "BlogPublication",
    "BlogImage",
    "CustomerWebsite",
    "CustomerSheetColumn",
    "CustomerSheetCell",
    "WebsiteKeyword",
    "SerpScan",
    "SerpScanResult",
    "WebsiteMetaRun",
    "WebsiteMetaPage",
    "BlogGenerationSettings",
    "UserAISettings",
    "WebsiteAudit",
    "AuditPage",
    "AuditIssue",
    "LaunchScan",
    "LaunchScanPage",
    "LaunchScanIssue",
    "LandingPageUpload",
    "LandingPageRow",
    "LandingPage",
    "LandingPageGenerationSettings",
]
