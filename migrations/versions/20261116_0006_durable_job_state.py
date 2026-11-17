"""Persist ingestion and execution job state.

Revision ID: 20261116_0006
Revises: 20261116_0005
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261116_0006"
down_revision = "20261116_0005"
branch_labels = None
depends_on = None


def _add_job_columns(table: str) -> None:
    op.add_column(
        table,
        sa.Column(
            "state", sa.String(length=32), server_default="queued", nullable=False
        ),
    )
    op.add_column(table, sa.Column("result_payload", postgresql.JSONB(), nullable=True))
    op.add_column(table, sa.Column("error", sa.Text(), nullable=True))
    op.add_column(table, sa.Column("error_code", sa.String(length=64), nullable=True))
    op.add_column(
        table, sa.Column("progress", sa.Float(), server_default="0", nullable=False)
    )
    op.add_column(
        table, sa.Column("message", sa.Text(), server_default="Queued", nullable=False)
    )
    op.add_column(
        table, sa.Column("attempt", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        table,
        sa.Column("max_attempts", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        table,
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def upgrade() -> None:
    _add_job_columns("ingestion_jobs")
    _add_job_columns("execution_jobs")


def _drop_job_columns(table: str) -> None:
    for column in (
        "updated_at",
        "max_attempts",
        "attempt",
        "message",
        "progress",
        "error_code",
        "error",
        "result_payload",
        "state",
    ):
        op.drop_column(table, column)


def downgrade() -> None:
    _drop_job_columns("execution_jobs")
    _drop_job_columns("ingestion_jobs")
