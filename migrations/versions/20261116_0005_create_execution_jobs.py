"""Create execution-job ownership mappings.

Revision ID: 20261116_0005
Revises: 20261116_0004
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261116_0005"
down_revision = "20261116_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_execution_jobs_owner_id", "execution_jobs", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_jobs_owner_id", table_name="execution_jobs")
    op.drop_table("execution_jobs")
