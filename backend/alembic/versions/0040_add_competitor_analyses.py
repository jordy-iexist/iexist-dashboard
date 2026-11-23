"""concurrentieanalyse per klant: runs, zoekwoorden, pagina's en verbeterpunten

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def upgrade() -> None:
    # Eén rij per run. Instellingen uit de wizard, voortgangstellers en het verbruik naast de
    # schatting. De vorm van de JSON-kolommen staat in features/competitor_analysis/schemas.py.
    op.create_table(
        "competitor_analyses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("country", sa.Text(), nullable=False),
        sa.Column("top_n", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("exclude_aggregators", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("modules", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("total_keywords", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("done_keywords", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_pages", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("fetched_pages", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_pages", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("vitals_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("vitals_measured", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ahrefs_units", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("ai_usage", sa.JSON(), nullable=True),
        sa.Column("estimate", sa.JSON(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_competitor_analyses_customer_website_id", "competitor_analyses", ["customer_website_id"]
    )

    # Per zoekwoord: SERP-gegevens, Google-poging (PAA, AI Overview) en de AI-uitkomst.
    # `target_url` leeg = er komt een nieuwe pagina.
    op.create_table(
        "competitor_analysis_keywords",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "analysis_id",
            sa.String(length=36),
            sa.ForeignKey("competitor_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column("keyword_key", sa.Text(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("own_position", sa.Integer(), nullable=True),
        sa.Column("own_position_source", sa.Text(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("kd", sa.Integer(), nullable=True),
        sa.Column("intents", sa.JSON(), nullable=True),
        sa.Column("serp_features", sa.JSON(), nullable=True),
        sa.Column("serp_date", sa.Text(), nullable=True),
        sa.Column("paa", sa.JSON(), nullable=True),
        sa.Column("ai_overview", sa.JSON(), nullable=True),
        sa.Column("ai_state", sa.Text(), nullable=True),
        sa.Column("ai_error", sa.Text(), nullable=True),
        sa.Column("serp_summary", sa.Text(), nullable=True),
        sa.Column("search_intent", sa.Text(), nullable=True),
        sa.Column("missing_topics", sa.JSON(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_competitor_analysis_keywords_analysis_id", "competitor_analysis_keywords", ["analysis_id"]
    )

    # Per zoekwoord per pagina (concurrent of eigen). De paginatekst wordt niet bewaard.
    op.create_table(
        "competitor_analysis_pages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "keyword_id",
            sa.String(length=36),
            sa.ForeignKey("competitor_analysis_keywords.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "analysis_id",
            sa.String(length=36),
            sa.ForeignKey("competitor_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_own", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_key", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("serp_title", sa.Text(), nullable=True),
        sa.Column("ahrefs_page_type", sa.Text(), nullable=True),
        sa.Column("page_type", sa.Text(), nullable=True),
        sa.Column("is_aggregator", sa.Boolean(), nullable=True),
        sa.Column("is_excluded", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("exclude_reason", sa.Text(), nullable=True),
        sa.Column("domain_rating", sa.Integer(), nullable=True),
        sa.Column("refdomains", sa.Integer(), nullable=True),
        sa.Column("ahrefs", sa.JSON(), nullable=True),
        sa.Column("fetch_status", sa.Text(), nullable=True),
        sa.Column("fetch_error", sa.Text(), nullable=True),
        sa.Column("onpage", sa.JSON(), nullable=True),
        sa.Column("eeat", sa.JSON(), nullable=True),
        sa.Column("lcp_ms", sa.Integer(), nullable=True),
        sa.Column("cwv", sa.JSON(), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_competitor_analysis_pages_keyword_id", "competitor_analysis_pages", ["keyword_id"]
    )
    op.create_index(
        "ix_competitor_analysis_pages_analysis_id", "competitor_analysis_pages", ["analysis_id"]
    )
    op.create_index("ix_competitor_analysis_pages_url_key", "competitor_analysis_pages", ["url_key"])

    # Verbeterpunten: eigen tabel, zodat afvinken één update is.
    op.create_table(
        "competitor_analysis_actions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "keyword_id",
            sa.String(length=36),
            sa.ForeignKey("competitor_analysis_keywords.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "analysis_id",
            sa.String(length=36),
            sa.ForeignKey("competitor_analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("impact", sa.Text(), nullable=True),
        sa.Column("effort", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("done_by", sa.String(length=36), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_competitor_analysis_actions_keyword_id", "competitor_analysis_actions", ["keyword_id"]
    )
    op.create_index(
        "ix_competitor_analysis_actions_analysis_id", "competitor_analysis_actions", ["analysis_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_competitor_analysis_actions_analysis_id", table_name="competitor_analysis_actions")
    op.drop_index("ix_competitor_analysis_actions_keyword_id", table_name="competitor_analysis_actions")
    op.drop_table("competitor_analysis_actions")
    op.drop_index("ix_competitor_analysis_pages_url_key", table_name="competitor_analysis_pages")
    op.drop_index("ix_competitor_analysis_pages_analysis_id", table_name="competitor_analysis_pages")
    op.drop_index("ix_competitor_analysis_pages_keyword_id", table_name="competitor_analysis_pages")
    op.drop_table("competitor_analysis_pages")
    op.drop_index("ix_competitor_analysis_keywords_analysis_id", table_name="competitor_analysis_keywords")
    op.drop_table("competitor_analysis_keywords")
    op.drop_index("ix_competitor_analyses_customer_website_id", table_name="competitor_analyses")
    op.drop_table("competitor_analyses")
