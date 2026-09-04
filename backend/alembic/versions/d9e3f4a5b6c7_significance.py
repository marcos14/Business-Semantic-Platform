"""relevância de negócio (significance) nos atoms e triviais descartados nos runs

Revision ID: d9e3f4a5b6c7
Revises: c8d2e3f4a5b6
Create Date: 2026-09-03 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd9e3f4a5b6c7'
down_revision: Union[str, None] = 'c8d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('knowledge_atoms', sa.Column('significance', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_knowledge_atoms_significance'), 'knowledge_atoms', ['significance'], unique=False)
    op.add_column(
        'discovery_runs',
        sa.Column('trivial_skipped', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('discovery_runs', 'trivial_skipped')
    op.drop_index(op.f('ix_knowledge_atoms_significance'), table_name='knowledge_atoms')
    op.drop_column('knowledge_atoms', 'significance')
