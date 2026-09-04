"""critério sistêmico: contador de runs renomeado (trivial_skipped → systemic_created)

Revision ID: e1f2a3b4c5d6
Revises: d9e3f4a5b6c7
Create Date: 2026-09-04 09:00:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd9e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('discovery_runs', 'trivial_skipped', new_column_name='systemic_created')
    # atoms marcados com o nome antigo passam ao critério sistêmico
    op.execute("UPDATE knowledge_atoms SET significance = 'SYSTEMIC' WHERE significance = 'TRIVIAL'")


def downgrade() -> None:
    op.execute("UPDATE knowledge_atoms SET significance = 'TRIVIAL' WHERE significance = 'SYSTEMIC'")
    op.alter_column('discovery_runs', 'systemic_created', new_column_name='trivial_skipped')
