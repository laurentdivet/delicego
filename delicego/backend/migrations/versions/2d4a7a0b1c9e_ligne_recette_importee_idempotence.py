"""ligne_recette_importee_idempotence

Revision ID: 2d4a7a0b1c9e
Revises: 1c2d3e4f5a6b
Create Date: 2026-02-02

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2d4a7a0b1c9e"
down_revision = "1c2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ajout ordre pour rendre le staging reconstructible et l'import idempotent.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.ligne_recette_importee') IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'ligne_recette_importee'
                      AND column_name = 'ordre'
                ) THEN
                    ALTER TABLE ligne_recette_importee ADD COLUMN ordre INTEGER;
                END IF;
            END IF;
        END $$;
        """
    )

    # Normalisation du statut mapping: contrainte CHECK simple (évite valeurs parasites)
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.ligne_recette_importee') IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'ck_ligne_recette_importee_statut_mapping'
                ) THEN
                    ALTER TABLE ligne_recette_importee
                    ADD CONSTRAINT ck_ligne_recette_importee_statut_mapping
                    CHECK (statut_mapping IN ('mapped','unmapped'));
                END IF;
            END IF;
        END $$;
        """
    )

    # Clé d'unicité retenue (déterministe) : (recette_id, pdf, ordre)
    # Hypothèse: l'import calcule ordre = index de ligne 0..N-1 pour chaque recette.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.ligne_recette_importee') IS NOT NULL THEN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'uq_ligne_recette_importee_recette_pdf_ordre'
                ) THEN
                    ALTER TABLE ligne_recette_importee
                    ADD CONSTRAINT uq_ligne_recette_importee_recette_pdf_ordre
                    UNIQUE (recette_id, pdf, ordre);
                END IF;
            END IF;
        END $$;
        """
    )

    # Index utiles
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.ligne_recette_importee') IS NOT NULL THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ligne_recette_importee_statut_mapping ON ligne_recette_importee (statut_mapping)';
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ligne_recette_importee_statut_mapping")
    op.execute("ALTER TABLE IF EXISTS ligne_recette_importee DROP CONSTRAINT IF EXISTS uq_ligne_recette_importee_recette_pdf_ordre")
    op.execute("ALTER TABLE IF EXISTS ligne_recette_importee DROP CONSTRAINT IF EXISTS ck_ligne_recette_importee_statut_mapping")
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.ligne_recette_importee') IS NOT NULL THEN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'ligne_recette_importee'
                      AND column_name = 'ordre'
                ) THEN
                    ALTER TABLE ligne_recette_importee DROP COLUMN ordre;
                END IF;
            END IF;
        END $$;
        """
    )
