"""add_prediction_vente_table

Revision ID: 9c1c1ab7b2c1
Revises: fb690cf04448
Create Date: 2026-01-28

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "9c1c1ab7b2c1"
down_revision = "fb690cf04448"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table de sortie des prédictions de ventes (inference ML)
    # - Unicité métier: (magasin_id, menu_id, date_jour)
    # - Upsert côté script via ON CONFLICT
    op.create_table(
        "prediction_vente",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("magasin_id", sa.UUID(), nullable=False),
        sa.Column("menu_id", sa.UUID(), nullable=False),
        sa.Column("date_jour", sa.Date(), nullable=False),
        sa.Column("qte_predite", sa.Float(), nullable=False),
        sa.Column("modele_version", sa.Text(), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mis_a_jour_le", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["magasin_id"], ["magasin.id"]),
        sa.ForeignKeyConstraint(["menu_id"], ["menu.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("magasin_id", "menu_id", "date_jour", name="uq_prediction_vente_magasin_menu_jour"),
    )
    op.create_index(
        "ix_prediction_vente_date_magasin",
        "prediction_vente",
        ["date_jour", "magasin_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_prediction_vente_date_magasin", table_name="prediction_vente")
    op.drop_table("prediction_vente")
