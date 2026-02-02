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
    # idempotence: colonne peut déjà exister sur certains environnements
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='menu'
                  AND column_name='gencode'
            ) THEN
                ALTER TABLE menu ADD COLUMN gencode VARCHAR(32);
            END IF;
        END $$;
        """
    )
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
    # 3) Contraintes : NOT NULL + UNIQUE + INDEX
    # idempotence: contrainte/index peuvent déjà exister selon les environnements
    op.alter_column("menu", "gencode", existing_type=sa.String(length=32), nullable=False)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname='uq_menu_gencode'
            ) THEN
                ALTER TABLE menu ADD CONSTRAINT uq_menu_gencode UNIQUE (gencode);
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_menu_gencode ON menu (gencode);
        """
    )


def downgrade() -> None:
    # idempotence
    op.execute("DROP INDEX IF EXISTS ix_menu_gencode")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname='uq_menu_gencode'
            ) THEN
                ALTER TABLE menu DROP CONSTRAINT uq_menu_gencode;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='menu'
                  AND column_name='gencode'
            ) THEN
                ALTER TABLE menu DROP COLUMN gencode;
            END IF;
        END $$;
        """
    )
