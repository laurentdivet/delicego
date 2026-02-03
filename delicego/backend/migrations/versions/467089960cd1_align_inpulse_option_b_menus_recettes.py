"""align inpulse option b menus->recettes

Revision ID: 467089960cd1
Revises: 06bfixmenusrecetteid
Create Date: 2025-12-16 07:28:53.830881

"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "467089960cd1"
down_revision = "06bfixmenusrecetteid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # a) Créer (si absentes) les recettes globales
    op.execute(
        """
        INSERT INTO recette (id, nom, cree_le, mis_a_jour_le)
        SELECT gen_random_uuid(), 'Riz cantonais', NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM recette WHERE nom = 'Riz cantonais');
        """
    )
    op.execute(
        """
        INSERT INTO recette (id, nom, cree_le, mis_a_jour_le)
        SELECT gen_random_uuid(), 'Pad Thaï crevettes', NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM recette WHERE nom = 'Pad Thaï crevettes');
        """
    )

    # b) Mettre à jour les menus existants (nom EXACT)
    op.execute(
        """
        UPDATE menu m
        SET recette_id = r.id
        FROM recette r
        WHERE m.nom = 'Riz cantonais'
          AND r.nom = 'Riz cantonais';
        """
    )
    op.execute(
        """
        UPDATE menu m
        SET recette_id = r.id
        FROM recette r
        WHERE m.nom = 'Pad Thaï crevettes'
          AND r.nom = 'Pad Thaï crevettes';
        """
    )

    # c) SI UN MENU A UN AUTRE NOM -> exception
    # IMPORTANT: en mode offline (--sql), pas de résultat Python. On génère donc un
    # guard SQL déterministe qui lève une exception côté Postgres.
    if context.is_offline_mode():
        op.execute(
            """
            DO $$
            DECLARE nb_autres integer;
            BEGIN
                SELECT count(*) INTO nb_autres
                FROM menu
                WHERE nom NOT IN ('Riz cantonais', 'Pad Thaï crevettes');
                IF nb_autres > 0 THEN
                    RAISE EXCEPTION 'Migration échouée: % menus ont un nom différent de ''Riz cantonais'' / ''Pad Thaï crevettes''.', nb_autres;
                END IF;
            END $$;
            """
        )
    else:
        res = op.get_bind().execute(
            sa.text(
                """
                SELECT count(*)
                FROM menu
                WHERE nom NOT IN ('Riz cantonais', 'Pad Thaï crevettes')
                """
            )
        )
        nb_autres = int(res.scalar() or 0)
        if nb_autres:
            raise RuntimeError(
                f"Migration échouée: {nb_autres} menus ont un nom différent de 'Riz cantonais' / 'Pad Thaï crevettes'."
            )

    # Ensuite seulement : rendre menu.recette_id NOT NULL
    op.alter_column("menu", "recette_id", existing_type=sa.UUID(), nullable=False)


def downgrade() -> None:
    # Revenir à un état permissif
    op.alter_column("menu", "recette_id", existing_type=sa.UUID(), nullable=True)
