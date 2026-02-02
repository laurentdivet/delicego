"""fix_produit_fournisseur_constraints

Revision ID: 95429d51e3b7
Revises: ddae8c2f594b
Create Date: 2026-01-26 12:28:45.575526

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


def _has_constraint(conn: sa.engine.Connection, table: str, constraint: str, ctype: str) -> bool:
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
    conn = op.get_bind()
    name = "uq_produit_fournisseur_produit_fournisseur"
    if _has_constraint(conn, "produit_fournisseur", name, "UNIQUE"):
        op.drop_constraint(
            name,
            "produit_fournisseur",
            type_="unique",
        )


def downgrade() -> None:
    conn = op.get_bind()
    name = "uq_produit_fournisseur_produit_fournisseur"
    if not _has_constraint(conn, "produit_fournisseur", name, "UNIQUE"):
        op.create_unique_constraint(
            name,
            "produit_fournisseur",
            ["produit_id", "fournisseur_id"],
        )
