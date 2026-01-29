"""add unique partial index uq_lpp_plan_menu_notnull

Revision ID: a4d553c4c000
Revises: d6d94cf88bc1
Create Date: 2026-01-28 20:47:39.317217

"""

from __future__ import annotations

from alembic import op



# revision identifiers, used by Alembic.
revision = 'a4d553c4c000'
down_revision = 'd6d94cf88bc1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres only
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_lpp_plan_menu_notnull
        ON ligne_plan_production(plan_production_id, menu_id)
        WHERE menu_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    # Postgres only
    op.execute("DROP INDEX IF EXISTS uq_lpp_plan_menu_notnull;")
