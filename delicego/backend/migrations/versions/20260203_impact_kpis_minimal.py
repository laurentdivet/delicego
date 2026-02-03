"""Impact KPIs minimal

Revision ID: 20260203_impact_kpis_minimal
Revises: zzzz_drop_native_enums_to_varchar
Create Date: 2026-02-03

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260203_impact_kpis_minimal"
down_revision = "zzzz_drop_native_enums"
branch_labels = None
depends_on = None


def _col_exists(bind, table: str, col: str) -> bool:
    insp = sa.inspect(bind)
    try:
        cols = insp.get_columns(table)
    except Exception:
        return False
    return any(c["name"] == col for c in cols)


def _table_exists(bind, table: str) -> bool:
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()

    # --- fournisseur: add region + distance_km (idempotent)
    if _table_exists(bind, "fournisseur"):
        if not _col_exists(bind, "fournisseur", "region"):
            op.add_column("fournisseur", sa.Column("region", sa.String(length=120), nullable=True))
        if not _col_exists(bind, "fournisseur", "distance_km"):
            op.add_column("fournisseur", sa.Column("distance_km", sa.Float(), nullable=True))

    # --- tables impact
    if not _table_exists(bind, "perte_casse"):
        op.create_table(
            "perte_casse",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("magasin_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("magasin.id"), nullable=False),
            sa.Column("ingredient_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("ingredient.id"), nullable=True),
            sa.Column("jour", sa.Date(), nullable=False),
            sa.Column("quantite", sa.Float(), nullable=False),
            sa.Column("unite", sa.String(length=50), nullable=False),
            sa.Column("cause", sa.String(length=200), nullable=True),
            sa.Column("creee_le", sa.DateTime(timezone=True), nullable=False),
            sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False),
            sa.Column("mis_a_jour_le", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_perte_casse_jour", "perte_casse", ["jour"], unique=False)
        op.create_index("ix_perte_casse_magasin_id", "perte_casse", ["magasin_id"], unique=False)

    if not _table_exists(bind, "facteur_co2"):
        op.create_table(
            "facteur_co2",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("categorie", sa.String(length=120), nullable=False, unique=True),
            sa.Column("facteur_kgco2e_par_kg", sa.Float(), nullable=False),
            sa.Column("source", sa.String(length=200), nullable=True),
            sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False),
            sa.Column("mis_a_jour_le", sa.DateTime(timezone=True), nullable=False),
        )

    if not _table_exists(bind, "ingredient_impact"):
        op.create_table(
            "ingredient_impact",
            sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "ingredient_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("ingredient.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("categorie_co2", sa.String(length=120), nullable=False),
            sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False),
            sa.Column("mis_a_jour_le", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_unique_constraint("uq_ingredient_impact_ingredient", "ingredient_impact", ["ingredient_id"])
        op.create_index("ix_ingredient_impact_categorie", "ingredient_impact", ["categorie_co2"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    # Drop impact tables (safe if missing)
    if _table_exists(bind, "ingredient_impact"):
        op.drop_index("ix_ingredient_impact_categorie", table_name="ingredient_impact")
        op.drop_constraint("uq_ingredient_impact_ingredient", "ingredient_impact", type_="unique")
        op.drop_table("ingredient_impact")

    if _table_exists(bind, "facteur_co2"):
        op.drop_table("facteur_co2")

    if _table_exists(bind, "perte_casse"):
        op.drop_index("ix_perte_casse_magasin_id", table_name="perte_casse")
        op.drop_index("ix_perte_casse_jour", table_name="perte_casse")
        op.drop_table("perte_casse")

    # Remove columns on fournisseur (safe if missing)
    if _table_exists(bind, "fournisseur"):
        if _col_exists(bind, "fournisseur", "distance_km"):
            op.drop_column("fournisseur", "distance_km")
        if _col_exists(bind, "fournisseur", "region"):
            op.drop_column("fournisseur", "region")
