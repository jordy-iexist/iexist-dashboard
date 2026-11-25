from __future__ import annotations

import secrets
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
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
    # Schrijfstijl voor teksten (content brief): vrije tekst en de aanspreekvorm "je" | "u".
    tone_of_voice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    form_of_address: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    # Klantprofiel (bedrijf, diensten en prijzen, USP's, bewijs, regels voor AI-content). De vorm
    # en het opschonen staan in features/customers/profile.py; lezen altijd via `parse_profile`.
    profile: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
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
    monday_group_fase4_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Groep van de livegangchecklist (livegangscans hebben phase = 5).
    monday_group_fase5_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Groep van de sitemap-monitor (monitorscans hebben phase = 6).
    monday_group_fase6_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Dagelijkse sitemap-monitor aan/uit voor deze klant. Standaard uit; gaat aan na de
    # eerste voltooide nulmeting (fase 1).
    sitemap_monitor_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Handmatig gekozen Search Console-property (bijv. "sc-domain:example.nl").
    # Leeg = automatisch zoeken op domein.
    gsc_property: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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


class OAuthConnection(Base):
    """Eén OAuth-koppeling voor de hele app, per externe dienst (nu: Bing Webmaster)."""

    __tablename__ = "oauth_connections"

    provider: Mapped[str] = mapped_column(String(50), primary_key=True)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # API en worker draaien los van elkaar: het access-token staat hier, niet in het proces.
    access_token_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    access_token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    connected_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # Gezet als verversen mislukt (toegang ingetrokken): de koppeling moet opnieuw.
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


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
    # Ahrefs-snapshot van het domein (fase 1): baseline, verbruik en herkomst.
    ahrefs: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Fase 4: Search Console-snapshot (prestaties, sitemaps, URL-inspectie).
    search_console: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Fase 4: Bing Webmaster-snapshot (index, crawlfouten, sitemaps, klikken).
    bing_webmaster: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Fase 1, 2 en 4: ProRankTracker-snapshot (AI-zichtbaarheid per platform en per prompt).
    proranktracker: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Fase 4: de ronde (kwartaal) waar de scan bij hoort, bijv. "2026-Q4".
    period: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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
    # Woorden buiten nav/header/footer/aside; NULL als de pagina geen van die elementen heeft.
    main_word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
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
    # Ahrefs: organisch verkeer en verwijzende domeinen per URL (scalair voor sorteren/filteren).
    org_traffic: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    refdomains: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ahrefs: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Gegenereerde JSON-LD ("Maak schema"): {jsonld, types, placeholders, notes, problems}.
    # Gaat niet mee naar een rescan.
    schema_suggestion: Mapped[Any] = mapped_column(JSON, nullable=True)
    schema_suggestion_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Eigen keuze van schema-types voor "Maak schema" (lijst met typenamen); None = automatisch
    # op paginatype. Gaat niet mee naar een rescan.
    schema_target_types: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LaunchChecklistState(Base):
    """Handmatige status per checklistpunt per klant (blijft over scans heen).

    `period` is leeg voor fase 2 en 3; fase 4 bewaart de status per ronde (kwartaal).
    """

    __tablename__ = "launch_checklist_states"
    __table_args__ = (
        UniqueConstraint(
            "customer_website_id", "item_key", "period", name="uq_launch_checklist_state"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_key: Mapped[str] = mapped_column(Text, nullable=False)
    period: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default=text("''")
    )
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
    # Gegenereerde opdracht voor Claude Code ("Maak prompt"); gaat niet mee naar een rescan.
    fix_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fix_prompt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class LaunchSitemapSnapshot(Base):
    """Laatst bekende sitemap-stand per klant voor de dagelijkse sitemap-monitor.

    `entries` is `{url_key: {"url": ..., "lastmod": ... | None}}`; `recent_changes`
    is een lijst `{"kind": "new" | "changed" | "removed", "url", "lastmod",
    "detected_at"}`, nieuwste eerst en begrensd (zie de monitorservice).
    """

    __tablename__ = "launch_sitemap_snapshots"

    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entries: Mapped[Any] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    recent_changes: Mapped[Any] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    # Laatste controle (ook zonder wijzigingen) en laatste keer dat er iets veranderde.
    checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Fout van de laatste run (lege/onbereikbare sitemap); leeg na een geslaagde run.
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CustomerQuickWins(Base):
    """Laatst opgehaalde Ahrefs-quick wins (positie 4–20) per klant voor het klantdashboard.

    `rows` is een lijst al omgezette rijen `{keyword, position, delta, volume, kd, url, kans}`
    in de volgorde van Ahrefs (volume aflopend). `target` en `country` horen bij de stand:
    wijzigt het domein of het land, dan wordt opnieuw opgehaald.
    """

    __tablename__ = "customer_quick_wins"

    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        primary_key=True,
    )
    target: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str] = mapped_column(Text, nullable=False)
    rows: Mapped[Any] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    # Verbruikte Ahrefs-units van de laatste geslaagde ophaalactie.
    units: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Laatste geslaagde ophaalactie (ook bij 0 rijen); leeg zolang er nooit iets is opgehaald.
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Fout van de laatste poging; leeg na een geslaagde ophaalactie.
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CustomerRankSnapshot(Base):
    """Dagelijkse momentopname van de ProRankTracker-posities per klant voor het bureau-overzicht.

    `state`: ok | not_configured | not_tracked | error (zoals de rankings van het klantdashboard).
    `keywords`, `top10` en `top10_month_ago` zijn alleen gevuld bij `ok`; `top10_month_ago` blijft
    leeg als ProRankTracker geen positie van een maand geleden gaf. `drops` is een lijst
    `{keyword, rank, month_ago_rank, url}` (grootste daling eerst; `rank` leeg = niet in de top 100).
    De regels staan in `features/agency_overview/services/rank_snapshots.py`.
    """

    __tablename__ = "customer_rank_snapshots"

    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        primary_key=True,
    )
    state: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    keywords: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    top10: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    top10_month_ago: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    drops: Mapped[Any] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    # Tijdstip van de laatste ophaalpoging (ook bij een fout).
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
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


class SiteChange(Base):
    """Beslissing of afhandeling van een medewerker over één voorstel of actiepunt op een pagina.

    Open punten zonder beslissing hebben geen rij. `source_key` is stabiel over herscans en
    heranalyses (issue-rijen en open voorstellen worden dan opnieuw aangemaakt); de rij bewaart
    genoeg om zelfstandig te tonen als de bronrij verdwenen is.
    `status`: goedgekeurd | afgewezen | doorgevoerd. `verified`: true = live teruggezien,
    false = gecontroleerd maar niet gevonden, None = niet (automatisch) gecontroleerd.
    """

    __tablename__ = "site_changes"
    __table_args__ = (
        UniqueConstraint("customer_website_id", "source_key", name="uq_site_change_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    # content_suggestion | scan_issue
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    # Vluchtige id's als hint: {"suggestion_id": ...} of {"issue_id": ...}.
    source_ref: Mapped[Any] = mapped_column(JSON, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    current_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proposed_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approved_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edited: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ref: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    item_label: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # {checked_at, message, live_value, missing}
    verify_detail: Mapped[Any] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CompetitorAnalysis(Base):
    """Eén run van de concurrentieanalyse voor een klant (één of meer zoekwoorden).

    De vorm van de JSON-kolommen staat in `features/competitor_analysis/schemas.py`:
    `modules` en `warnings` zijn lijsten, `sources` is `Sources`, `estimate` is `Estimate`,
    `ai_usage` is `AiUsage`. Medianen worden niet opgeslagen maar bij het lezen berekend.
    """

    __tablename__ = "competitor_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    # pending | serp | fetching | analyzing | completed | failed | canceled
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warnings: Mapped[Any] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    # Instellingen uit de wizard.
    country: Mapped[str] = mapped_column(Text, nullable=False)
    top_n: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default=text("10")
    )
    exclude_aggregators: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    modules: Mapped[Any] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    # Voortgangstellers.
    total_keywords: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    done_keywords: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    total_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    fetched_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    failed_pages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    vitals_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    vitals_measured: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Werkelijk verbruik naast de schatting vooraf.
    ahrefs_units: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    ai_usage: Mapped[Any] = mapped_column(JSON, nullable=True)
    estimate: Mapped[Any] = mapped_column(JSON, nullable=True)
    sources: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CompetitorAnalysisKeyword(Base):
    """Eén zoekwoord binnen een concurrentieanalyse, met de SERP-gegevens en de AI-uitkomst.

    `target_url` leeg = er komt een nieuwe pagina (geen eigen pagina om te vergelijken).
    `keyword_key` is het genormaliseerde zoekwoord (`customers.rankings.keyword_key`).
    """

    __tablename__ = "competitor_analysis_keywords"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("competitor_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    keyword: Mapped[str] = mapped_column(Text, nullable=False)
    keyword_key: Mapped[str] = mapped_column(Text, nullable=False)
    target_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    own_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # prt | ahrefs
    own_position_source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kd: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Lijst van actieve intenties (namen), lijst van SERP-featuretypes.
    intents: Mapped[Any] = mapped_column(JSON, nullable=True)
    serp_features: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Datum van de SERP-stand zoals Ahrefs hem geeft (ISO-tekst).
    serp_date: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # `Paa` en `AiOverview` uit de eigen Google-poging (of Ahrefs).
    paa: Mapped[Any] = mapped_column(JSON, nullable=True)
    ai_overview: Mapped[Any] = mapped_column(JSON, nullable=True)
    # ok | not_configured | error | skipped; leeg zolang de AI-stap nog niet gedraaid heeft.
    ai_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    serp_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    search_intent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Lijst van `MissingTopic`.
    missing_topics: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Volledige onderwerpenlijst: lijst van `TopicCoverage`. Leeg (None) bij analyses van vóór
    # migratie 0041; de content brief valt dan terug op `missing_topics`.
    topics: Mapped[Any] = mapped_column(JSON, nullable=True)
    # pending | completed | failed
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CompetitorAnalysisPage(Base):
    """Eén pagina bij één zoekwoord: een concurrent uit de top X of de eigen doelpagina.

    De paginatekst wordt niet bewaard; alleen de uitgelezen kenmerken (`onpage` = `OnPage`,
    `eeat` = `Eeat`, `cwv` = `Cwv`). `ahrefs` bewaart de overige Ahrefs-velden van de SERP-rij.
    """

    __tablename__ = "competitor_analysis_pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    keyword_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("competitor_analysis_keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("competitor_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_own: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Positie in de SERP; leeg voor een eigen pagina buiten de top X.
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_key: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    final_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    domain: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    serp_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Ruwe Ahrefs-waarde; `page_type` is de eigen indeling (dienst | product | ... | overig).
    ahrefs_page_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Vergelijkingssite of gids; leeg zolang de pagina nog niet is ingedeeld.
    is_aggregator: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    # Telt niet mee in de medianen.
    is_excluded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # aggregator | own_site
    exclude_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    domain_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    refdomains: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ahrefs: Mapped[Any] = mapped_column(JSON, nullable=True)
    # ok | blocked | not_html | error; leeg zolang de pagina nog niet is opgehaald.
    fetch_status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fetch_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    onpage: Mapped[Any] = mapped_column(JSON, nullable=True)
    eeat: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Lab-meting mobiel (ms), scalair voor de mediaan; details in `cwv`.
    lcp_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cwv: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CompetitorAnalysisAction(Base):
    """Verbeterpunt bij één zoekwoord. Eigen tabel, zodat afvinken één update is.

    `impact` en `effort`: hoog | middel | laag. `category`: een van de modules
    (serp | onpage | topics | authority | tech | eeat).
    """

    __tablename__ = "competitor_analysis_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    keyword_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("competitor_analysis_keywords.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("competitor_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    impact: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effort: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    done: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    done_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ContentBrief(Base):
    """Content brief en concepttekst voor één zoekwoord uit een concurrentieanalyse.

    Eén per zoekwoord (`keyword_id` uniek). `brief` is `Brief`, `concept` is `Concept`,
    `ai_usage` is `AiUsage` (opgeteld over alle aanroepen, ook "concept opnieuw"); de vormen
    staan in `features/competitor_analysis/schemas.py`. Eigen status, los van de analyse.
    """

    __tablename__ = "content_briefs"
    __table_args__ = (
        UniqueConstraint("keyword_id", name="uq_content_briefs_keyword_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    keyword_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("competitor_analysis_keywords.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("competitor_analyses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # pending | brief | concept | completed | failed
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    brief: Mapped[Any] = mapped_column(JSON, nullable=True)
    concept: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Model van de laatste geslaagde aanroep (bij een server-side fallback het werkelijke model).
    model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_usage: Mapped[Any] = mapped_column(JSON, nullable=True)
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


class MonthlyReport(Base):
    """Maandrapport van één klant voor één kalendermaand ("YYYY-MM").

    Eén per klant en maand. `data` is `ReportData` (momentopname van cijfers en werk), `report`
    is `ReportText` (tekst van de agent), `manual` is `Manual` (handmatige cijfers, alleen door
    de router geschreven), `ai_usage` is `AiUsage`; de vormen staan in
    `features/monthly_report/schemas.py`. `data` en `report` worden samen weggeschreven.
    """

    __tablename__ = "monthly_reports"
    __table_args__ = (
        UniqueConstraint("customer_website_id", "month", name="uq_monthly_reports_customer_month"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
    )
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    # draft | pending | collecting | writing | completed | failed
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data: Mapped[Any] = mapped_column(JSON, nullable=True)
    report: Mapped[Any] = mapped_column(JSON, nullable=True)
    manual: Mapped[Any] = mapped_column(JSON, nullable=True)
    ai_usage: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Model van de laatste geslaagde aanroep.
    model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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


class WorkItem(Base):
    """Kaart op de werkvoorraad: een gebundelde groep punten uit één bron, of een eigen taak.

    `source`: scan | analysis | search_console | site_changes | manual. `group_key` is de vaste
    sleutel van de groep binnen (klant, bron); leeg bij een eigen taak. `active_key` is gelijk
    aan `group_key` zolang de kaart in todo/doing/review staat en anders NULL, zodat er per
    groep hooguit één open kaart is en afgeronde of verwijderde kaarten blijven bestaan.
    `status`: todo | doing | review | done | removed. `kind`: ctr | techniek | content | links |
    update | rapport. `severity`: hoog | middel | laag. `items` is een momentopname: lijst van
    `{key, title, url, severity, ref, suppress_key}` (zie `features/work_queue/services/types.py`).
    `resolved_by_source`: vanzelf afgerond omdat de bron niets open meer heeft.
    """

    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("customer_website_id", "source", "active_key", name="uq_work_item_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    customer_website_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("customer_websites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    group_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    active_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="todo", server_default=text("'todo'"), index=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Zonder aantal; de frontend zet `item_count` en de eenheid erachter.
    title: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        Text, nullable=False, default="middel", server_default=text("'middel'")
    )
    item_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Zwaar; alleen laden waar de lijst nodig is (detail, sync bij een gewijzigde groep).
    items: Mapped[Any] = mapped_column(JSON, nullable=True, deferred=True)
    # sha1 over de itemsleutels en de ernst; gelijk = niets bijwerken.
    fingerprint: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    # Volgorde binnen de kolom (oplopend); slepen zet de positie tussen de buren.
    position: Mapped[float] = mapped_column(Float, nullable=False)
    assignee_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by_source: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    # Leeg = automatisch aangemaakt door de synchronisatie.
    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
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
    "SiteChange",
    "CompetitorAnalysis",
    "CompetitorAnalysisKeyword",
    "CompetitorAnalysisPage",
    "CompetitorAnalysisAction",
    "ContentBrief",
    "MonthlyReport",
    "WorkItem",
    "CustomerRankSnapshot",
]
