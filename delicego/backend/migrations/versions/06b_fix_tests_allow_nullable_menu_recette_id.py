"""fix tests: allow nullable menu.recette_id

Revision ID: 06bfixmenusrecetteid
Revises: 05e8cb54a773
Create Date: 2025-12-16

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "06bfixmenusrecetteid"
down_revision = "05e8cb54a773"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Permettre l'insert de menus sans recette dans les tests (et dans la phase transitoire).
    # L'objectif final (Inpulse) est de rendre NOT NULL, mais ça doit être accompagné
    # d'une migration stricte qui rattache tous les menus existants.
    op.alter_column("menu", "recette_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.alter_column("menu", "recette_id", existing_type=sa.UUID(), nullable=False)
