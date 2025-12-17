"""add audit_log

Revision ID: fb690cf04448
Revises: fa67a615428c
Create Date: 2025-12-16 21:03:40.515676

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql



# revision identifiers, used by Alembic.
revision = 'fb690cf04448'
down_revision = 'fa67a615428c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "cree_le",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("ressource", sa.String(length=120), nullable=False),
        sa.Column("ressource_id", sa.String(length=120), nullable=True),
        sa.Column("methode_http", sa.String(length=20), nullable=True),
        sa.Column("chemin", sa.String(length=300), nullable=True),
        sa.Column("statut_http", sa.Integer(), nullable=True),
        sa.Column("donnees", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(length=60), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_audit_log_user_id_user"),
    )
    op.create_index("ix_audit_log_user_id", "audit_log", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_log_user_id", table_name="audit_log")
    op.drop_table("audit_log")
