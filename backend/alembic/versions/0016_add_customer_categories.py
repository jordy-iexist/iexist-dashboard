"""add customer_categories table and category_id on customer_websites

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-13
"""
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_categories",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
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
        sa.UniqueConstraint("name", name="uq_customer_categories_name"),
    )

    op.add_column(
        "customer_websites",
        sa.Column("category_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_customer_websites_category_id",
        "customer_websites",
        "customer_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_customer_websites_category_id",
        "customer_websites",
        ["category_id"],
    )

    # Data migration: turn existing free-text `industry` values into
    # CustomerCategory rows and point customer_websites.category_id at them.
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, industry, created_by
            FROM customer_websites
            WHERE industry IS NOT NULL AND trim(industry) <> ''
            ORDER BY created_at ASC
            """
        )
    ).fetchall()

    categories_by_key: dict[str, dict[str, str]] = {}
    for row in rows:
        raw_name = (row.industry or "").strip()
        key = raw_name.lower()
        if key not in categories_by_key:
            categories_by_key[key] = {
                "id": str(uuid.uuid4()),
                "name": raw_name,
                "created_by": row.created_by,
            }

    for category in categories_by_key.values():
        bind.execute(
            sa.text(
                """
                INSERT INTO customer_categories (id, name, created_by, created_at, updated_at)
                VALUES (:id, :name, :created_by, now(), now())
                """
            ),
            category,
        )

    for row in rows:
        key = (row.industry or "").strip().lower()
        category_id = categories_by_key[key]["id"]
        bind.execute(
            sa.text(
                "UPDATE customer_websites SET category_id = :category_id WHERE id = :id"
            ),
            {"category_id": category_id, "id": row.id},
        )

    op.drop_column("customer_websites", "industry")


def downgrade() -> None:
    op.add_column(
        "customer_websites",
        sa.Column("industry", sa.Text(), nullable=True),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE customer_websites
            SET industry = customer_categories.name
            FROM customer_categories
            WHERE customer_websites.category_id = customer_categories.id
            """
        )
    )

    op.drop_index("ix_customer_websites_category_id", table_name="customer_websites")
    op.drop_constraint(
        "fk_customer_websites_category_id",
        "customer_websites",
        type_="foreignkey",
    )
    op.drop_column("customer_websites", "category_id")

    op.drop_table("customer_categories")
