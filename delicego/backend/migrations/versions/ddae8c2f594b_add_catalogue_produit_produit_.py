"""add_catalogue_produit_produit_fournisseur_and_ingredient_link

Revision ID: ddae8c2f594b
Revises: e770a91fe2c0
Create Date: 2026-01-26 12:16:43.835178

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'ddae8c2f594b'
down_revision = 'e770a91fe2c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # MIGRATION MANUELLE (anti-régression)
    # L'autogenerate a détecté beaucoup de deltas hors-sujet (tables existantes
    # non présentes dans la DB locale, anciennes colonnes/constraints, etc.).
    # Pour éviter toute régression, on limite STRICTEMENT cette migration à:
    # - création des tables produit + produit_fournisseur
    # - ajout du lien optionnel ingredient -> produit + champs conversion

    op.create_table(
        "produit",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("libelle", sa.String(length=250), nullable=False, comment="Nom métier unique du produit."),
        sa.Column("categorie", sa.String(length=120), nullable=True),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mis_a_jour_le", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("libelle", name="uq_produit_libelle"),
    )
    op.create_index("ix_produit_libelle", "produit", ["libelle"], unique=False)

    op.create_table(
        "produit_fournisseur",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("produit_id", sa.UUID(), nullable=False),
        sa.Column("fournisseur_id", sa.UUID(), nullable=False),
        sa.Column("reference_fournisseur", sa.String(length=120), nullable=False, comment="SKU / référence chez le fournisseur"),
        sa.Column("libelle_fournisseur", sa.String(length=250), nullable=True),
        sa.Column("unite_achat", sa.String(length=50), nullable=False, comment="Unité d'achat (kg, pièce, carton, sac, bidon, etc.)"),
        sa.Column("quantite_par_unite", sa.Float(), nullable=False, server_default=sa.text("1"), comment="Quantité contenue dans l'unité d'achat (ex: 20 pour SAC 20KG)."),
        sa.Column("prix_achat_ht", sa.Numeric(precision=12, scale=4), nullable=True, comment="Prix HT pour l'unité d'achat."),
        sa.Column("tva", sa.Numeric(precision=5, scale=4), nullable=True, comment="Taux de TVA (ex: 0.055, 0.10, 0.20)."),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("cree_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mis_a_jour_le", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["produit_id"], ["produit.id"], name="fk_produit_fournisseur_produit_id"),
        sa.ForeignKeyConstraint(["fournisseur_id"], ["fournisseur.id"], name="fk_produit_fournisseur_fournisseur_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fournisseur_id", "reference_fournisseur", name="uq_produit_fournisseur_sku"),
    )
    op.create_index("ix_produit_fournisseur_produit_id", "produit_fournisseur", ["produit_id"], unique=False)
    op.create_index("ix_produit_fournisseur_fournisseur_id", "produit_fournisseur", ["fournisseur_id"], unique=False)

    # Ingredient: champs nullable pour compat ascendante.
    # idempotence: certains environnements ont déjà ces colonnes.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='ingredient' AND column_name='produit_id'
            ) THEN
                ALTER TABLE ingredient ADD COLUMN produit_id UUID;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='ingredient' AND column_name='unite_consommation'
            ) THEN
                ALTER TABLE ingredient ADD COLUMN unite_consommation VARCHAR(50);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema='public' AND table_name='ingredient' AND column_name='facteur_conversion'
            ) THEN
                ALTER TABLE ingredient ADD COLUMN facteur_conversion DOUBLE PRECISION;
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
                SELECT 1 FROM pg_constraint WHERE conname='fk_ingredient_produit_id'
            ) THEN
                ALTER TABLE ingredient
                    ADD CONSTRAINT fk_ingredient_produit_id
                    FOREIGN KEY (produit_id) REFERENCES produit(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ingredient_produit_id ON ingredient (produit_id);")


def downgrade() -> None:
    # idempotence
    op.execute("DROP INDEX IF EXISTS ix_ingredient_produit_id")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_ingredient_produit_id') THEN
                ALTER TABLE ingredient DROP CONSTRAINT fk_ingredient_produit_id;
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='ingredient' AND column_name='facteur_conversion') THEN
                ALTER TABLE ingredient DROP COLUMN facteur_conversion;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='ingredient' AND column_name='unite_consommation') THEN
                ALTER TABLE ingredient DROP COLUMN unite_consommation;
            END IF;
            IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='ingredient' AND column_name='produit_id') THEN
                ALTER TABLE ingredient DROP COLUMN produit_id;
            END IF;
        END $$;
        """
    )

    op.drop_index("ix_produit_fournisseur_fournisseur_id", table_name="produit_fournisseur")
    op.drop_index("ix_produit_fournisseur_produit_id", table_name="produit_fournisseur")
    op.drop_table("produit_fournisseur")

    op.drop_index("ix_produit_libelle", table_name="produit")
    op.drop_table("produit")
