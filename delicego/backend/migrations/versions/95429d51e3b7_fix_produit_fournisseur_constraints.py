"""fix_produit_fournisseur_constraints

Revision ID: 95429d51e3b7
Revises: ddae8c2f594b
Create Date: 2026-01-26 12:28:45.575526

"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


def _has_constraint(conn: sa.engine.Connection, table: str, constraint: str, ctype: str) -> bool:
    # En mode offline (--sql), impossible d'interroger la DB. On renvoie False;
    # la migration émettra un DROP CONSTRAINT conditionnel via SQL.
    if context.is_offline_mode():
        return False
    return (
        conn.execute(
            sa.text(
                """
                select 1
                from information_schema.table_constraints
                where table_schema='public'
                  and table_name=:t
                  and constraint_name=:c
                  and constraint_type=:ct
                """
            ),
            {"t": table, "c": constraint, "ct": ctype},
        ).scalar()
        is not None
    )



# revision identifiers, used by Alembic.
revision = '95429d51e3b7'
down_revision = 'ddae8c2f594b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # L'ancienne migration autogénérée avait une contrainte UNIQUE(produit_id, fournisseur_id)
    # qui est invalide fonctionnellement (un fournisseur vend plusieurs produits).
    # On la supprime si elle existe.
    name = "uq_produit_fournisseur_produit_fournisseur"
    if context.is_offline_mode():
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE table_schema='public'
                      AND table_name='produit_fournisseur'
                      AND constraint_name='{name}'
                      AND constraint_type='UNIQUE'
                ) THEN
                    ALTER TABLE produit_fournisseur DROP CONSTRAINT {name};
                END IF;
            END $$;
            """
        )
    else:
        conn = op.get_bind()
        if _has_constraint(conn, "produit_fournisseur", name, "UNIQUE"):
            op.drop_constraint(
                name,
                "produit_fournisseur",
                type_="unique",
            )


def downgrade() -> None:
    name = "uq_produit_fournisseur_produit_fournisseur"
    if context.is_offline_mode():
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints
                    WHERE table_schema='public'
                      AND table_name='produit_fournisseur'
                      AND constraint_name='{name}'
                      AND constraint_type='UNIQUE'
                ) THEN
                    ALTER TABLE produit_fournisseur
                    ADD CONSTRAINT {name} UNIQUE (produit_id, fournisseur_id);
                END IF;
            END $$;
            """
        )
    else:
        conn = op.get_bind()
        if not _has_constraint(conn, "produit_fournisseur", name, "UNIQUE"):
            op.create_unique_constraint(
                name,
                "produit_fournisseur",
                ["produit_id", "fournisseur_id"],
            )
