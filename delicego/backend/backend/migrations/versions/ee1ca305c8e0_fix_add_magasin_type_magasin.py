"""fix add magasin.type_magasin

Revision ID: ee1ca305c8e0
Revises: 434746e12d2a
Create Date: 2026-02-02
"""
from alembic import op
import sqlalchemy as sa

revision = "ee1ca305c8e0"
down_revision = "434746e12d2a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "magasin",
        sa.Column("type_magasin", sa.String(length=50), nullable=True),
    )


def downgrade():
    op.drop_column("magasin", "type_magasin")
