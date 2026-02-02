"""add_ingredient_alias_table

Revision ID: 0f7b3df3c6a1
Revises: 2b5f0e1a4d11
Create Date: 2026-02-02

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0f7b3df3c6a1"
down_revision = "2b5f0e1a4d11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Hypothèse raisonnable: on est sur PostgreSQL (UUID natif).
    # Contrainte forte: ne jamais créer d'ingrédients fantômes -> table d'alias dédiée.
    # idempotence: la table peut déjà exister sur certains environnements.
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.ingredient_alias') IS NULL THEN
                CREATE TABLE ingredient_alias (
                    id UUID NOT NULL,
                    alias TEXT NOT NULL,
                    alias_normalise TEXT NOT NULL,
                    ingredient_id UUID NOT NULL REFERENCES ingredient(id) ON DELETE RESTRICT,
                    source VARCHAR(30) NOT NULL,
                    actif BOOLEAN NOT NULL DEFAULT true,
                    cree_le TIMESTAMPTZ NOT NULL,
                    mis_a_jour_le TIMESTAMPTZ NOT NULL,
                    CONSTRAINT uq_ingredient_alias_alias_normalise UNIQUE (alias_normalise),
                    PRIMARY KEY (id)
                );
            END IF;

            -- Index (non unique)
            EXECUTE 'CREATE INDEX IF NOT EXISTS ix_ingredient_alias_alias_normalise ON ingredient_alias (alias_normalise)';

            -- Retire le défaut DB sur actif si présent
            ALTER TABLE ingredient_alias ALTER COLUMN actif DROP DEFAULT;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ingredient_alias_alias_normalise")
    op.execute("DROP TABLE IF EXISTS ingredient_alias")
