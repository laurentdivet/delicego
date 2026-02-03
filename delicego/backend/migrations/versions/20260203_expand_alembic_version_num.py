"""fix: expand alembic_version.version_num to varchar(64)

Revision ID: 20260203_expand_alembic_version_num
Revises: 53582036ad5f
Create Date: 2026-02-03

Rationale:
The project uses human-readable revision ids (e.g. 20260203_impact_actions_exploitables)
which exceed Alembic's default VARCHAR(32) for alembic_version.version_num.
On a fresh DB, Alembic will create alembic_version with VARCHAR(32) and then fail
when upgrading to longer revision ids.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260203_expand_alembic_version_num"
down_revision = "cb98e890d546"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ensure alembic_version exists, then expand column.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema='public' AND table_name='alembic_version'
            ) THEN
                CREATE TABLE alembic_version (
                    version_num VARCHAR(32) NOT NULL,
                    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
                );
            END IF;

            ALTER TABLE alembic_version
            ALTER COLUMN version_num TYPE VARCHAR(64);
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(32);")
