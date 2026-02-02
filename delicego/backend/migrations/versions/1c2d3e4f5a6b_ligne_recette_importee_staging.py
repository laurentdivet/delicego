"""ligne_recette_importee_staging

Revision ID: 1c2d3e4f5a6b
Revises: 0f7b3df3c6a1
Create Date: 2026-02-02

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "1c2d3e4f5a6b"
down_revision = "0f7b3df3c6a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Choix structurel (contrainte): ligne_recette.ingredient_id est NOT NULL.
    # Pour conserver 100% des infos PDF, on crée une table de staging d'import.
    # idempotence: la table peut déjà exister sur certains environnements.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.ligne_recette_importee') IS NULL THEN
                CREATE TABLE ligne_recette_importee (
                    id UUID NOT NULL,
                    recette_id UUID NOT NULL REFERENCES recette(id) ON DELETE CASCADE,
                    pdf TEXT NOT NULL,
                    ingredient_brut TEXT NOT NULL,
                    ingredient_normalise TEXT NOT NULL,
                    quantite DOUBLE PRECISION NOT NULL,
                    unite VARCHAR(50) NOT NULL,
                    ingredient_id UUID REFERENCES ingredient(id) ON DELETE RESTRICT,
                    ordre INTEGER,
                    statut_mapping VARCHAR(20) NOT NULL,
                    cree_le TIMESTAMPTZ NOT NULL,
                    mis_a_jour_le TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (id)
                );
            END IF;

            EXECUTE 'CREATE INDEX IF NOT EXISTS ix_lri_recette_id ON ligne_recette_importee (recette_id)';
            EXECUTE 'CREATE INDEX IF NOT EXISTS ix_lri_statu_mapping ON ligne_recette_importee (statut_mapping)';
            EXECUTE 'CREATE INDEX IF NOT EXISTS ix_lri_ingredient_normalise ON ligne_recette_importee (ingredient_normalise)';
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_lri_ingredient_normalise")
    op.execute("DROP INDEX IF EXISTS ix_lri_statu_mapping")
    op.execute("DROP INDEX IF EXISTS ix_lri_recette_id")
    op.execute("DROP TABLE IF EXISTS ligne_recette_importee")
