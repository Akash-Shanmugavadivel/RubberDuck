"""Create pgvector collection, document, and chunk storage.

Revision ID: 20261116_0003
Revises: 20261116_0002
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "20261116_0003"
down_revision = "20261116_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vector_collections",
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("embedding_identity", sa.String(length=255), nullable=False),
        sa.Column("index_schema_version", sa.String(length=32), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "vector_documents",
        sa.Column("collection_name", sa.String(length=63), nullable=False),
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["collection_name"], ["vector_collections.name"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("collection_name", "id"),
    )
    op.create_table(
        "vector_chunks",
        sa.Column("collection_name", sa.String(length=63), nullable=False),
        sa.Column("id", sa.String(length=512), nullable=False),
        sa.Column("document_id", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chunk_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["collection_name", "document_id"],
            ["vector_documents.collection_name", "vector_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("collection_name", "id"),
    )
    op.create_index(
        "ix_vector_chunks_document_id",
        "vector_chunks",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_vector_chunks_document_id", table_name="vector_chunks")
    op.drop_table("vector_chunks")
    op.drop_table("vector_documents")
    op.drop_table("vector_collections")
