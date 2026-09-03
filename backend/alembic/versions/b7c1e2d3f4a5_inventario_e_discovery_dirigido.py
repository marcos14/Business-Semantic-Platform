"""inventário de fontes e discovery dirigido

Revision ID: b7c1e2d3f4a5
Revises: 9e630ee9403e
Create Date: 2026-09-03 09:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b7c1e2d3f4a5'
down_revision: Union[str, None] = '9e630ee9403e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('capabilities', sa.Column('description', sa.Text(), nullable=True))

    op.add_column('discovery_runs', sa.Column('batch_id', sa.Uuid(), nullable=True))
    op.add_column('discovery_runs', sa.Column('target_file', sa.String(length=1000), nullable=True))
    op.add_column('discovery_runs', sa.Column('line_range', sa.String(length=40), nullable=True))
    op.create_index(op.f('ix_discovery_runs_batch_id'), 'discovery_runs', ['batch_id'], unique=False)

    op.create_table('source_files',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('path', sa.String(length=1000), nullable=False),
    sa.Column('language', sa.String(length=40), nullable=True),
    sa.Column('lines', sa.Integer(), nullable=False),
    sa.Column('chars', sa.Integer(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('commit', sa.String(length=100), nullable=True),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('inventoried_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_id', 'path', name='uq_source_files_source_path')
    )
    op.create_index(op.f('ix_source_files_source_id'), 'source_files', ['source_id'], unique=False)

    op.create_table('source_file_capabilities',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('file_id', sa.Uuid(), nullable=False),
    sa.Column('capability_slug', sa.String(length=100), nullable=False),
    sa.Column('relevance', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['capability_slug'], ['capabilities.slug'], ),
    sa.ForeignKeyConstraint(['file_id'], ['source_files.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('file_id', 'capability_slug', name='uq_source_file_capability')
    )
    op.create_index(op.f('ix_source_file_capabilities_file_id'), 'source_file_capabilities', ['file_id'], unique=False)
    op.create_index(op.f('ix_source_file_capabilities_capability_slug'), 'source_file_capabilities', ['capability_slug'], unique=False)

    op.create_table('capability_suggestions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.Uuid(), nullable=False),
    sa.Column('domain_slug', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=True),
    sa.Column('example_files', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('hits', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_id', 'domain_slug', 'name', name='uq_capability_suggestion')
    )
    op.create_index(op.f('ix_capability_suggestions_source_id'), 'capability_suggestions', ['source_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_capability_suggestions_source_id'), table_name='capability_suggestions')
    op.drop_table('capability_suggestions')
    op.drop_index(op.f('ix_source_file_capabilities_capability_slug'), table_name='source_file_capabilities')
    op.drop_index(op.f('ix_source_file_capabilities_file_id'), table_name='source_file_capabilities')
    op.drop_table('source_file_capabilities')
    op.drop_index(op.f('ix_source_files_source_id'), table_name='source_files')
    op.drop_table('source_files')
    op.drop_index(op.f('ix_discovery_runs_batch_id'), table_name='discovery_runs')
    op.drop_column('discovery_runs', 'line_range')
    op.drop_column('discovery_runs', 'target_file')
    op.drop_column('discovery_runs', 'batch_id')
    op.drop_column('capabilities', 'description')
