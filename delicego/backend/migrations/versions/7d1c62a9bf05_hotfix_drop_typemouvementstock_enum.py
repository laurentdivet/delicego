"""hotfix_drop_typemouvementstock_enum

Revision ID: 7d1c62a9bf05
Revises: zzzz_drop_native_enums
Create Date: 2026-02-02 18:03:18.457331

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = '7d1c62a9bf05'
down_revision = 'zzzz_drop_native_enums'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Hotfix idempotent: certains environnements héritent encore de l'ENUM natif
    # `typemouvementstock` (créé dans la migration initiale) sur
    # `public.mouvement_stock.type_mouvement`.
    #
    # Stratégie "Solution 2": Enum Python + stockage VARCHAR en DB => aucun ENUM PG natif.
    op.execute(
        """
        DO $$
        BEGIN
            -- 1) Convertir la colonne si elle est encore USER-DEFINED
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name='mouvement_stock'
                  AND column_name='type_mouvement'
                  AND data_type='USER-DEFINED'
            ) THEN
                ALTER TABLE public.mouvement_stock
                ALTER COLUMN type_mouvement TYPE VARCHAR(50)
                USING type_mouvement::text;
            END IF;

            -- 2) Drop du type ENUM s'il existe (devrait être non référencé après conversion)
            IF EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE n.nspname='public'
                  AND t.typname='typemouvementstock'
            ) THEN
                DROP TYPE public.typemouvementstock;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("downgrade not supported (solution 2)")
