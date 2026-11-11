"""livegang: punten doorzetten naar Monday

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-11
"""
import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_CUSTOMER_COLUMNS = (
    "monday_board_id",
    "monday_board_url",
    "monday_group_fase1_id",
    "monday_group_fase2_id",
)
_STATE_TEXT_COLUMNS = ("external_provider", "external_item_id", "external_url")


def upgrade() -> None:
    # Eén Monday-bord per klant, met een groep per fase.
    for name in _CUSTOMER_COLUMNS:
        op.add_column("customer_websites", sa.Column(name, sa.Text(), nullable=True))

    # Zelfde koppelvelden als launch_scan_issues, nu ook per checklistpunt.
    for name in _STATE_TEXT_COLUMNS:
        op.add_column("launch_checklist_states", sa.Column(name, sa.Text(), nullable=True))
    op.add_column(
        "launch_checklist_states",
        sa.Column("pushed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("launch_checklist_states", "pushed_at")
    for name in reversed(_STATE_TEXT_COLUMNS):
        op.drop_column("launch_checklist_states", name)
    for name in reversed(_CUSTOMER_COLUMNS):
        op.drop_column("customer_websites", name)
