from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import text

revision = "ee1ca305c8e0"
down_revision = "434746e12d2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # add only if missing
    if context.is_offline_mode():
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='magasin'
                      AND column_name='type_magasin'
                ) THEN
                    ALTER TABLE magasin ADD COLUMN type_magasin varchar(50);
                END IF;
            END $$;
            """
        )
    else:
        bind = op.get_bind()
        exists = bind.execute(
            text(
                """
                select 1
                from information_schema.columns
                where table_schema='public'
                  and table_name='magasin'
                  and column_name='type_magasin'
                """
            )
        ).first()

        if not exists:
            op.add_column("magasin", sa.Column("type_magasin", sa.String(length=50), nullable=True))


def downgrade() -> None:
    # drop only if present
    if context.is_offline_mode():
        op.execute(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='magasin'
                      AND column_name='type_magasin'
                ) THEN
                    ALTER TABLE magasin DROP COLUMN type_magasin;
                END IF;
            END $$;
            """
        )
    else:
        bind = op.get_bind()
        exists = bind.execute(
            text(
                """
                select 1
                from information_schema.columns
                where table_schema='public'
                  and table_name='magasin'
                  and column_name='type_magasin'
                """
            )
        ).first()

        if exists:
            op.drop_column("magasin", "type_magasin")
