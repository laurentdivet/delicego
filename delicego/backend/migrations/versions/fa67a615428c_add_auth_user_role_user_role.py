"""add auth user role user_role

Revision ID: fa67a615428c
Revises: 467089960cd1
Create Date: 2025-12-16 21:02:39.001040

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql



# revision identifiers, used by Alembic.
revision = 'fa67a615428c'
down_revision = '467089960cd1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "role",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("libelle", sa.String(length=120), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "cree_le",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column(
            "mis_a_jour_le",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.UniqueConstraint("code", name="uq_role_code"),
    )
    op.create_index("ix_role_code", "role", ["code"], unique=True)

    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("nom_affiche", sa.String(length=200), nullable=False),
        sa.Column("mot_de_passe_hash", sa.String(length=255), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("dernier_login_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cree_le",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column(
            "mis_a_jour_le",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.UniqueConstraint("email", name="uq_user_email"),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    op.create_table(
        "user_role",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "cree_le",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column(
            "mis_a_jour_le",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name="fk_user_role_role_id_role"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_user_role_user_id_user"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role_user_id_role_id"),
    )
    op.create_index("ix_user_role_user_id", "user_role", ["user_id"], unique=False)
    op.create_index("ix_user_role_role_id", "user_role", ["role_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_user_role_role_id", table_name="user_role")
    op.drop_index("ix_user_role_user_id", table_name="user_role")
    op.drop_table("user_role")

    op.drop_index("ix_user_email", table_name="user")
    op.drop_table("user")

    op.drop_index("ix_role_code", table_name="role")
    op.drop_table("role")
