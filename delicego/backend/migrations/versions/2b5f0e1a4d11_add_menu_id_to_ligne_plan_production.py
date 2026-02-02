"""add menu_id to ligne_plan_production

Revision ID: 2b5f0e1a4d11
Revises: 1e28a4774db8
Create Date: 2026-01-28

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2b5f0e1a4d11"
down_revision = "1e28a4774db8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Ajout colonne nullable (transition safe)
    # idempotence: certains environnements ont déjà menu_id
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='ligne_plan_production'
                  AND column_name='menu_id'
            ) THEN
                ALTER TABLE ligne_plan_production ADD COLUMN menu_id UUID;
            END IF;
        END $$;
        """
    )

    # FK + index: idempotence
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_schema='public'
                  AND table_name='ligne_plan_production'
                  AND constraint_name='fk_ligne_plan_production_menu_id_menu'
                  AND constraint_type='FOREIGN KEY'
            ) THEN
                ALTER TABLE ligne_plan_production
                    ADD CONSTRAINT fk_ligne_plan_production_menu_id_menu
                    FOREIGN KEY (menu_id) REFERENCES menu(id);
            END IF;
        END $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ligne_plan_production_menu_id ON ligne_plan_production (menu_id);")

    # 2) Contrainte unique partielle (optionnel mais utile). Multiple NULL autorisés.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_ligne_plan_production_plan_menu
        ON ligne_plan_production (plan_production_id, menu_id)
        WHERE menu_id IS NOT NULL;
        """
    )

    # 3) Backfill menu_id quand l'association recette->menu est non ambiguë dans le magasin du plan
    #    - pp.magasin_id permet de restreindre
    #    - si 0 ou >1 menu pour une recette => on laisse NULL
    op.execute(
        """
        WITH c AS (
          SELECT
            lpp.id AS lpp_id,
            (array_agg(m.id ORDER BY m.id))[1] AS menu_id,
            COUNT(m.id) AS cnt
          FROM ligne_plan_production lpp
          JOIN plan_production pp ON pp.id = lpp.plan_production_id
          JOIN menu m ON m.magasin_id = pp.magasin_id AND m.recette_id = lpp.recette_id
          WHERE lpp.menu_id IS NULL
          GROUP BY lpp.id
        )
        UPDATE ligne_plan_production lpp
        SET menu_id = c.menu_id
        FROM c
        WHERE lpp.id = c.lpp_id
          AND c.cnt = 1;
        """
    )


def downgrade() -> None:
    # Drop index/constraint then column (idempotent)
    op.execute("DROP INDEX IF EXISTS uq_ligne_plan_production_plan_menu")
    op.execute("DROP INDEX IF EXISTS ix_ligne_plan_production_menu_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.table_constraints
                WHERE table_schema='public'
                  AND table_name='ligne_plan_production'
                  AND constraint_name='fk_ligne_plan_production_menu_id_menu'
                  AND constraint_type='FOREIGN KEY'
            ) THEN
                ALTER TABLE ligne_plan_production DROP CONSTRAINT fk_ligne_plan_production_menu_id_menu;
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
                  AND table_name='ligne_plan_production'
                  AND column_name='menu_id'
            ) THEN
                ALTER TABLE ligne_plan_production DROP COLUMN menu_id;
            END IF;
        END $$;
        """
    )
