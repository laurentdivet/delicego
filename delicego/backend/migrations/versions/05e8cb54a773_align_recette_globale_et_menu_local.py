"""align recette globale et menu local

Revision ID: 05e8cb54a773
Revises: cd1233d73e50
Create Date: 2025-12-16 07:03:13.137448

"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = '05e8cb54a773'
down_revision = 'cd1233d73e50'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Ajouter menu.recette_id (nullable temporairement pour migration data)
    op.add_column("menu", sa.Column("recette_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_menu_recette_id", "menu", "recette", ["recette_id"], ["id"])

    # 2) Migrer les données existantes :
    # 2.1) Cas historique : menu.recette_id = recette.id via recette.menu_id
    # NOTE:
    # En base neuve (migration_initiale récente), la colonne recette.menu_id peut ne plus exister.
    # On protège donc l'UPDATE pour rester compatible.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name='recette' AND column_name='menu_id'
            ) THEN
                UPDATE menu m
                SET recette_id = r.id
                FROM recette r
                WHERE r.menu_id = m.id;
            END IF;
        END $$;
        """
    )

    # 2.2) Cas "menus orphelins" (validé) :
    # Créer 2 recettes globales (unicité par nom exact) puis rattacher tous les menus par nom exact.
    # AUCUNE déduction : si un menu n'a pas de recette après ces règles => on échoue plus bas.

    # Crée (si absent) la recette globale "Riz cantonais"
    # NOTE : en base ancienne, recette.magasin_id est NOT NULL => on ne peut pas insérer sans magasin.
    # Pour une base neuve (vide), cette partie est inutile : aucun menu à rattacher.
    op.execute(
        """
        DO $$
        DECLARE nb_menus integer;
        BEGIN
            SELECT count(*) INTO nb_menus FROM menu;
            IF nb_menus > 0 THEN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='recette' AND column_name='menu_id'
                ) THEN
                    INSERT INTO recette (id, nom, menu_id, cree_le, mis_a_jour_le)
                    SELECT gen_random_uuid(), 'Riz cantonais', NULL, NOW(), NOW()
                    WHERE NOT EXISTS (SELECT 1 FROM recette WHERE nom = 'Riz cantonais');
                ELSE
                    INSERT INTO recette (id, nom, cree_le, mis_a_jour_le)
                    SELECT gen_random_uuid(), 'Riz cantonais', NOW(), NOW()
                    WHERE NOT EXISTS (SELECT 1 FROM recette WHERE nom = 'Riz cantonais');
                END IF;
            END IF;
        END $$;
        """
    )

    # Crée (si absent) la recette globale "Pad Thaï crevettes"
    op.execute(
        """
        DO $$
        DECLARE nb_menus integer;
        BEGIN
            SELECT count(*) INTO nb_menus FROM menu;
            IF nb_menus > 0 THEN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name='recette' AND column_name='menu_id'
                ) THEN
                    INSERT INTO recette (id, nom, menu_id, cree_le, mis_a_jour_le)
                    SELECT gen_random_uuid(), 'Pad Thaï crevettes', NULL, NOW(), NOW()
                    WHERE NOT EXISTS (SELECT 1 FROM recette WHERE nom = 'Pad Thaï crevettes');
                ELSE
                    INSERT INTO recette (id, nom, cree_le, mis_a_jour_le)
                    SELECT gen_random_uuid(), 'Pad Thaï crevettes', NOW(), NOW()
                    WHERE NOT EXISTS (SELECT 1 FROM recette WHERE nom = 'Pad Thaï crevettes');
                END IF;
            END IF;
        END $$;
        """
    )

    # Rattache les menus "Riz cantonais" (nom EXACT)
    op.execute(
        """
        UPDATE menu m
        SET recette_id = r.id
        FROM recette r
        WHERE m.recette_id IS NULL
          AND m.nom = 'Riz cantonais'
          AND r.nom = 'Riz cantonais'
        """
    )

    # Rattache les menus "Pad Thaï crevettes" (nom EXACT)
    op.execute(
        """
        UPDATE menu m
        SET recette_id = r.id
        FROM recette r
        WHERE m.recette_id IS NULL
          AND m.nom = 'Pad Thaï crevettes'
          AND r.nom = 'Pad Thaï crevettes'
        """
    )

    # 3) Garde-fou : on refuse de rendre NOT NULL si des menus n'ont pas de recette.
    # IMPORTANT: en mode offline (--sql), il est impossible d'exécuter un SELECT et de
    # récupérer un résultat côté Python. On émet donc un bloc SQL déterministe qui
    # lève une exception côté Postgres si la condition n'est pas respectée.
    if context.is_offline_mode():
        op.execute(
            """
            DO $$
            DECLARE nb_null integer;
            BEGIN
                SELECT count(*) INTO nb_null FROM menu WHERE recette_id IS NULL;
                IF nb_null > 0 THEN
                    RAISE EXCEPTION 'Migration impossible: % menus n''ont pas de recette associée. Corriger les données (ou supprimer ces menus) avant de continuer.', nb_null;
                END IF;
            END $$;
            """
        )
    else:
        res = op.get_bind().execute(sa.text("select count(*) from menu where recette_id is null"))
        nb_null = int(res.scalar() or 0)
        if nb_null:
            raise RuntimeError(
                f"Migration impossible: {nb_null} menus n'ont pas de recette associée. "
                "Corriger les données (ou supprimer ces menus) avant de continuer."
            )

    op.alter_column("menu", "recette_id", existing_type=sa.UUID(), nullable=False)

    # 4) Recette devient globale
    # - recette.menu_id devient nullable
    # - et on supprime la contrainte FK vers menu pour éviter une dépendance circulaire
    #   (menu -> recette_id est désormais la source de vérité).
    # La contrainte recette_menu_id_fkey peut ne pas exister selon les historiques de schéma.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'recette_menu_id_fkey'
            ) THEN
                ALTER TABLE recette DROP CONSTRAINT recette_menu_id_fkey;
            END IF;
        END $$;
        """
    )

    # menu_id peut déjà être absent dans certains schémas.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name='recette' AND column_name='menu_id'
            ) THEN
                ALTER TABLE recette ALTER COLUMN menu_id DROP NOT NULL;
            END IF;
        END $$;
        """
    )

    # - supprimer recette.magasin_id (et son index + FK)
    op.drop_index("ix_recette_magasin_id", table_name="recette")
    op.drop_constraint("recette_magasin_id_fkey", "recette", type_="foreignkey")
    op.drop_column("recette", "magasin_id")


def downgrade() -> None:
    # Recréer recette.magasin_id (nullable temporairement)
    op.add_column("recette", sa.Column("magasin_id", sa.UUID(), nullable=True))
    op.create_foreign_key("recette_magasin_id_fkey", "recette", "magasin", ["magasin_id"], ["id"])
    op.create_index("ix_recette_magasin_id", "recette", ["magasin_id"], unique=False)

    # Remigrer recette.menu_id + recette.magasin_id depuis menu.recette_id
    # Hypothèse downgrade : un seul menu par recette (sinon on prend le premier arbitrairement)
    op.execute(
        """
        UPDATE recette r
        SET menu_id = sub.menu_id,
            magasin_id = sub.magasin_id
        FROM (
            SELECT DISTINCT ON (m.recette_id)
                m.recette_id,
                m.id as menu_id,
                m.magasin_id
            FROM menu m
            WHERE m.recette_id IS NOT NULL
            ORDER BY m.recette_id, m.id
        ) sub
        WHERE r.id = sub.recette_id
        """
    )

    # Rendre recette.menu_id NOT NULL
    op.alter_column("recette", "menu_id", existing_type=sa.UUID(), nullable=False)

    # Supprimer menu.recette_id
    op.drop_constraint("fk_menu_recette_id", "menu", type_="foreignkey")
    op.drop_column("menu", "recette_id")
