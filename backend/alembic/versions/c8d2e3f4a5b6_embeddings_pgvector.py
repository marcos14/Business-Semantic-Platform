"""embeddings dos atoms (pgvector) e contador de reforços nos runs

Revision ID: c8d2e3f4a5b6
Revises: b7c1e2d3f4a5
Create Date: 2026-09-03 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = 'c8d2e3f4a5b6'
down_revision: Union[str, None] = 'b7c1e2d3f4a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DIM = 1536  # openai/text-embedding-3-small


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table('atom_embeddings',
    sa.Column('atom_id', sa.String(length=300), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('text_hash', sa.String(length=32), nullable=False),
    sa.Column('embedding', Vector(DIM), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['atom_id'], ['knowledge_atoms.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('atom_id')
    )
    # HNSW por cosseno: busca aproximada rápida mesmo com dezenas de milhares de atoms
    op.execute(
        "CREATE INDEX ix_atom_embeddings_hnsw ON atom_embeddings "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.add_column(
        'discovery_runs',
        sa.Column('reinforcements', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('discovery_runs', 'reinforcements')
    op.execute("DROP INDEX IF EXISTS ix_atom_embeddings_hnsw")
    op.drop_table('atom_embeddings')
