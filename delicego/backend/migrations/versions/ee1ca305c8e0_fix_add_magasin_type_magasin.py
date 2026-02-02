from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "ee1ca305c8e0"
down_revision = "434746e12d2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # add only if missing
    bind = op.get_bind()
    exists = bind.execute(
        text("""
            select 1
            from information_schema.columns
            where table_schema='public'
              and table_name='magasin'
              and column_name='type_magasin'
        """)
    ).first()

    if not exists:
        op.add_column("magasin", sa.Column("type_magasin", sa.String(length=50), nullable=True))


def downgrade() -> None:
    # drop only if present
    bind = op.get_bind()
    exists = bind.execute(
        text("""
            select 1
            from information_schema.columns
            where table_schema='public'
              and table_name='magasin'
              and column_name='type_magasin'
        """)
    ).first()

    if exists:
        op.drop_column("magasin", "type_magasin")
