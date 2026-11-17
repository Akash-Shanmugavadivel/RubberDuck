"""Enable the pgvector PostgreSQL extension.

Revision ID: 20261116_0001
Revises:
Create Date: 2026-11-16
"""

from alembic import op

revision = "20261116_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Other applications may share this extension; never remove it automatically.
    pass
