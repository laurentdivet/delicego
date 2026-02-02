"""Drop native PostgreSQL ENUM usage (migrate to VARCHAR) + remove enum types.

Revision ID: zzzz_drop_native_enums_to_varchar
Revises: ee1ca305c8e0
Create Date: 2026-02-02

STRATEGY (imposed): Enum Python in app, stored as VARCHAR in DB (native_enum=False everywhere).

This migration:
- Converts all columns currently backed by PostgreSQL ENUM types to VARCHAR.
- Drops the ENUM types once no longer referenced.

Idempotence:
- Uses IF EXISTS guards and checks information_schema before altering.

WARNING:
- Requires an exclusive lock while altering column types.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# IMPORTANT: Alembic stores revision ids in alembic_version.version_num which is VARCHAR(32) by default.
# So revision ids MUST be <= 32 chars.
revision = "zzzz_drop_native_enums"
down_revision = "ee1ca305c8e0"
branch_labels = None
depends_on = None


def _col_is_enum(table: str, column: str, udt_name: str) -> bool:
    res = op.get_bind().execute(
        sa.text(
            """
            select 1
            from information_schema.columns
            where table_schema='public'
              and table_name=:t
              and column_name=:c
              and data_type='USER-DEFINED'
              and udt_name=:u
            """
        ),
        {"t": table, "c": column, "u": udt_name},
    ).scalar()
    return res is not None


def _alter_enum_to_varchar(table: str, column: str, udt_name: str, varchar_len: int = 50) -> None:
    # Only alter if the column is currently backed by the expected enum type.
    if not _col_is_enum(table, column, udt_name):
        return
    op.execute(
        sa.text(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE VARCHAR({varchar_len}) USING {column}::text"
        )
    )


def _drop_type_if_exists(type_name: str) -> None:
    # Drop enum type only if present and no longer referenced.
    # CASCADE is intentionally NOT used.
    op.execute(sa.text(f"DROP TYPE IF EXISTS {type_name}"))


def upgrade() -> None:
    # Convert columns (current schema from psql introspection)
    _alter_enum_to_varchar("magasin", "type_magasin", "type_magasin", varchar_len=50)
    # NB: l'enum natif vient de la migration initiale avec name='typemouvementstock'
    # (et non 'type_mouvement_stock'). On convertit donc ce type.
    _alter_enum_to_varchar("mouvement_stock", "type_mouvement", "typemouvementstock", varchar_len=50)
    _alter_enum_to_varchar("plan_production", "statut", "statutplanproduction", varchar_len=50)
    _alter_enum_to_varchar("vente", "canal", "canalvente", varchar_len=50)
    _alter_enum_to_varchar("commande_client", "statut", "statut_commande_client", varchar_len=50)
    _alter_enum_to_varchar("commande_fournisseur", "statut", "statut_commande_fournisseur", varchar_len=50)
    _alter_enum_to_varchar("ecriture_comptable", "type", "type_ecriture_comptable", varchar_len=50)
    _alter_enum_to_varchar("equipement_thermique", "type_equipement", "typeequipementthermique", varchar_len=50)
    _alter_enum_to_varchar("equipement_thermique", "zone", "zoneequipementthermique", varchar_len=50)

    # Drop enum types now unused.
    # NOTE: order doesn't matter once columns are converted.
    _drop_type_if_exists("type_magasin")
    _drop_type_if_exists("typemouvementstock")
    _drop_type_if_exists("statutplanproduction")
    _drop_type_if_exists("canalvente")
    _drop_type_if_exists("statut_commande_client")
    _drop_type_if_exists("statut_commande_fournisseur")
    _drop_type_if_exists("type_ecriture_comptable")
    _drop_type_if_exists("typeequipementthermique")
    _drop_type_if_exists("zoneequipementthermique")


def downgrade() -> None:
    # Non-reversible by design.
    # Recreating native enums would require reconstructing types + exact labels + casting.
    raise RuntimeError("Non réversible: migration de ENUM natif -> VARCHAR (stratégie native_enum=False).")
