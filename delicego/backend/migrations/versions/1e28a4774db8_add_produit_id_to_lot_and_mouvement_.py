"""add produit_id to lot and mouvement_stock

Revision ID: 1e28a4774db8
Revises: 95429d51e3b7
Create Date: 2026-01-26 13:26:11.328107

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


def _has_column(conn: sa.engine.Connection, table: str, column: str) -> bool:
    return (
        conn.execute(
            sa.text(
                """
                select 1
                from information_schema.columns
                where table_schema='public'
                  and table_name=:t
                  and column_name=:c
                """
            ),
            {"t": table, "c": column},
        ).scalar()
        is not None
    )


def _has_index(conn: sa.engine.Connection, index_name: str) -> bool:
    return (
        conn.execute(
            sa.text(
                """
                select 1
                from pg_indexes
                where schemaname='public'
                  and indexname=:i
                """
            ),
            {"i": index_name},
        ).scalar()
        is not None
    )


def _has_fk(conn: sa.engine.Connection, table: str, fk_name: str) -> bool:
    return (
        conn.execute(
            sa.text(
                """
                select 1
                from information_schema.table_constraints
                where table_schema='public'
                  and table_name=:t
                  and constraint_name=:c
                  and constraint_type='FOREIGN KEY'
                """
            ),
            {"t": table, "c": fk_name},
        ).scalar()
        is not None
    )


def _fk_name(table: str) -> str:
    return f"{table}_produit_id_fkey"


def _ix_name(table: str) -> str:
    return f"ix_{table}_produit_id"



# revision identifiers, used by Alembic.
revision = '1e28a4774db8'
down_revision = '95429d51e3b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Phase A : ajout compatible (nullable) + index + FK vers produit.id.

    Migration **idempotente** : si le schéma existe déjà (ex: base locale bricolée),
    les opérations deviennent des no-op.
    """

    conn = op.get_bind()

    if not _has_column(conn, "lot", "produit_id"):
        op.add_column("lot", sa.Column("produit_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    if not _has_column(conn, "mouvement_stock", "produit_id"):
        op.add_column(
            "mouvement_stock",
            sa.Column("produit_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        )

    ix_lot = _ix_name("lot")
    ix_ms = _ix_name("mouvement_stock")
    if not _has_index(conn, ix_lot):
        op.create_index(ix_lot, "lot", ["produit_id"], unique=False)
    if not _has_index(conn, ix_ms):
        op.create_index(ix_ms, "mouvement_stock", ["produit_id"], unique=False)

    fk_lot = _fk_name("lot")
    fk_ms = _fk_name("mouvement_stock")
    if not _has_fk(conn, "lot", fk_lot):
        op.create_foreign_key(fk_lot, "lot", "produit", ["produit_id"], ["id"], ondelete="SET NULL")
    if not _has_fk(conn, "mouvement_stock", fk_ms):
        op.create_foreign_key(
            fk_ms,
            "mouvement_stock",
            "produit",
            ["produit_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    conn = op.get_bind()

    fk_ms = _fk_name("mouvement_stock")
    fk_lot = _fk_name("lot")
    if _has_fk(conn, "mouvement_stock", fk_ms):
        op.drop_constraint(fk_ms, "mouvement_stock", type_="foreignkey")
    if _has_fk(conn, "lot", fk_lot):
        op.drop_constraint(fk_lot, "lot", type_="foreignkey")

    ix_ms = _ix_name("mouvement_stock")
    ix_lot = _ix_name("lot")
    if _has_index(conn, ix_ms):
        op.drop_index(ix_ms, table_name="mouvement_stock")
    if _has_index(conn, ix_lot):
        op.drop_index(ix_lot, table_name="lot")

    if _has_column(conn, "mouvement_stock", "produit_id"):
        op.drop_column("mouvement_stock", "produit_id")
    if _has_column(conn, "lot", "produit_id"):
        op.drop_column("lot", "produit_id")
