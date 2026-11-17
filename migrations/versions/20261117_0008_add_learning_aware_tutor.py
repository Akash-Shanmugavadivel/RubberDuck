"""Add learning-aware tutor behavior and instructor policy.

Revision ID: 20261117_0008
Revises: 20261117_0007
Create Date: 2026-11-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261117_0008"
down_revision = "20261117_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "role", sa.String(length=16), server_default="student", nullable=False
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "behavior", sa.String(length=32), server_default="explain", nullable=False
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "difficulty",
            sa.String(length=32),
            server_default="intermediate",
            nullable=False,
        ),
    )
    op.create_table(
        "tutor_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "allow_direct_answers", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column(
            "allow_code_solutions", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("hints_only", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        sa.text(
            "INSERT INTO tutor_policy "
            "(id, allow_direct_answers, allow_code_solutions, hints_only) "
            "VALUES (1, true, true, false)"
        )
    )


def downgrade() -> None:
    op.drop_table("tutor_policy")
    op.drop_column("conversations", "difficulty")
    op.drop_column("conversations", "behavior")
    op.drop_column("users", "role")
