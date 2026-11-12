"""livegang fase 4: kwartaal GEO-werkzaamheden (rondes per kwartaal)

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ronde (kwartaal) van een fase 4-scan, bijv. "2026-Q4". Leeg voor fase 1-3.
    op.add_column("launch_scans", sa.Column("period", sa.Text(), nullable=True))

    # Handmatige status per ronde. Fase 2 en 3 houden een lege ronde (''), zodat hun
    # status per klant blijft gelden zoals voorheen.
    op.add_column(
        "launch_checklist_states",
        sa.Column("period", sa.Text(), nullable=False, server_default=sa.text("''")),
    )
    op.drop_constraint("uq_launch_checklist_state", "launch_checklist_states", type_="unique")
    op.create_unique_constraint(
        "uq_launch_checklist_state",
        "launch_checklist_states",
        ["customer_website_id", "item_key", "period"],
    )

    op.add_column(
        "customer_websites", sa.Column("monday_group_fase4_id", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("customer_websites", "monday_group_fase4_id")
    # Rondes van fase 4 passen niet in de oude unieke sleutel.
    op.execute("DELETE FROM launch_checklist_states WHERE period <> ''")
    op.drop_constraint("uq_launch_checklist_state", "launch_checklist_states", type_="unique")
    op.create_unique_constraint(
        "uq_launch_checklist_state",
        "launch_checklist_states",
        ["customer_website_id", "item_key"],
    )
    op.drop_column("launch_checklist_states", "period")
    op.drop_column("launch_scans", "period")
