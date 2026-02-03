"""merge heads

Revision ID: cb98e890d546
Revises: 20260203_impact_kpis_minimal, 7d1c62a9bf05
Create Date: 2026-02-03 05:10:32.074271

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = 'cb98e890d546'
down_revision = ('20260203_impact_kpis_minimal', '7d1c62a9bf05')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
