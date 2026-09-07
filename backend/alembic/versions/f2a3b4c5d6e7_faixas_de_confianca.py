"""faixas de confiança: status PROVISIONAL, perfil de evidência por domain, piso provisório
nas políticas, perfil gravado no score e políticas iniciais por relevância

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-07 09:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_ACTOR = 'system:migration'


def _seed_policy(name, scope_type, selector, threshold, human, min_rev, owner, floor):
    def _v(x):
        if x is None:
            return 'null'
        if isinstance(x, bool):
            return 'true' if x else 'false'
        return repr(x)
    op.execute(
        f"""
        insert into policies (id, name, scope_type, selector, threshold, human_review_required,
                              min_reviewers, require_owner_approval, provisional_floor, active,
                              created_by, created_at, updated_at)
        select gen_random_uuid(), {_v(name)}, {_v(scope_type)}, {_v(selector)}, {_v(threshold)},
               {_v(human)}, {_v(min_rev)}, {_v(owner)}, {_v(floor)}, true, {_v(_SEED_ACTOR)},
               now(), now()
        where not exists (
            select 1 from policies where scope_type = {_v(scope_type)} and selector = {_v(selector)}
        )
        """
    )


def upgrade() -> None:
    op.add_column('domains', sa.Column('evidence_profile', sa.String(length=40), nullable=True))
    op.add_column('policies', sa.Column('provisional_floor', sa.Float(), nullable=True))
    op.add_column('confidence_scores', sa.Column('profile', sa.String(length=40), nullable=True))
    # Políticas iniciais por relevância (idempotentes: só se não houver uma para o escopo).
    # MEDIUM: canônico a 70%, provisório a 40%, um revisor basta (owner dispensado).
    _seed_policy(
        'Relevância MEDIUM — canônico 70%, provisório 40%, um revisor basta',
        'significance', 'MEDIUM', 0.70, None, 1, False, 0.40,
    )
    # HIGH (dinheiro, imposto, estoque): canônico a 85%, provisório a 55%, owner obrigatório.
    _seed_policy(
        'Relevância HIGH — canônico 85%, provisório 55%, owner aprova',
        'significance', 'HIGH', 0.85, None, None, True, 0.55,
    )
    # Risco CRITICAL: revisão humana obrigatória, sempre.
    _seed_policy(
        'Risco CRITICAL — revisão humana obrigatória',
        'risk', 'CRITICAL', None, True, None, True, None,
    )


def downgrade() -> None:
    op.execute(f"delete from policies where created_by = '{_SEED_ACTOR}'")
    op.drop_column('confidence_scores', 'profile')
    op.drop_column('policies', 'provisional_floor')
    op.drop_column('domains', 'evidence_profile')
