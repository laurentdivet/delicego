"""add_menu_gencode

Revision ID: e770a91fe2c0
Revises: fb690cf04448
Create Date: 2025-12-21 08:39:44.201774

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = 'e770a91fe2c0'
down_revision = 'fb690cf04448'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Ajout du champ en nullable pour permettre un backfill.
    op.add_column("menu", sa.Column("gencode", sa.String(length=32), nullable=True))

    # 2) Backfill minimal : si la table contient déjà des lignes, on génère un gencode
    # déterministe et unique à partir de l'ID.
    #
    # IMPORTANT :
    # - Ce gencode est une clé technique de transition.
    # - En production, il devra être remplacé par le vrai gencode (EAN/UPC) de l'étiquette.
    # - L'application n'affiche jamais ce champ.
    # On tronque l'UUID (sans '-') pour rester <= 32 caractères.
    op.execute(
        "UPDATE menu SET gencode = 'AUTO-' || left(replace(id::text, '-', ''), 27) WHERE gencode IS NULL"
    )

    # 3) Contraintes : NOT NULL + UNIQUE + INDEX
    op.alter_column("menu", "gencode", existing_type=sa.String(length=32), nullable=False)
    op.create_unique_constraint("uq_menu_gencode", "menu", ["gencode"])
    op.create_index("ix_menu_gencode", "menu", ["gencode"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_menu_gencode", table_name="menu")
    op.drop_constraint("uq_menu_gencode", "menu", type_="unique")
    op.drop_column("menu", "gencode")
