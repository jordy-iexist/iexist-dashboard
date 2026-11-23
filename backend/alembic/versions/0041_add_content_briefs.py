"""content brief + concepttekst per zoekwoord, volledige onderwerpenlijst, schrijfstijl per klant

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Eén brief per zoekwoord van een concurrentieanalyse, met een eigen status en eigen
    # kostenregistratie (los van de analyse). De vorm van `brief`, `concept` en `ai_usage` staat
    # in features/competitor_analysis/schemas.py.
    op.create_table(
        "content_briefs",
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
        sa.Column(
            "customer_website_id",
            sa.String(length=36),
            sa.ForeignKey("customer_websites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("brief", sa.JSON(), nullable=True),
        sa.Column("concept", sa.JSON(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("ai_usage", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("keyword_id", name="uq_content_briefs_keyword_id"),
    )
    op.create_index("ix_content_briefs_analysis_id", "content_briefs", ["analysis_id"])
    op.create_index("ix_content_briefs_customer_website_id", "content_briefs", ["customer_website_id"])

    # De volledige onderwerpenlijst van aanroep B (tot nu toe bleven alleen de ontbrekende over).
    # Leeg bij oude analyses: de brief valt dan terug op `missing_topics`.
    op.add_column("competitor_analysis_keywords", sa.Column("topics", sa.JSON(), nullable=True))

    # Schrijfstijl per klant: de brief-agent volgt deze letterlijk. `form_of_address`: "je" | "u".
    op.add_column("customer_websites", sa.Column("tone_of_voice", sa.Text(), nullable=True))
    op.add_column("customer_websites", sa.Column("form_of_address", sa.String(length=2), nullable=True))


def downgrade() -> None:
    op.drop_column("customer_websites", "form_of_address")
    op.drop_column("customer_websites", "tone_of_voice")
    op.drop_column("competitor_analysis_keywords", "topics")
    op.drop_index("ix_content_briefs_customer_website_id", table_name="content_briefs")
    op.drop_index("ix_content_briefs_analysis_id", table_name="content_briefs")
    op.drop_table("content_briefs")
