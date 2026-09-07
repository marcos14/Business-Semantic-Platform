"""help desk semantic consumption, feedback and freshness

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-09-07 13:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "helpdesk_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("consumer_profile", sa.String(length=40), nullable=False),
        sa.Column("scope_type", sa.String(length=30), nullable=False),
        sa.Column("selector", sa.String(length=200), nullable=True),
        sa.Column("allowed_statuses", postgresql.JSONB(), nullable=False),
        sa.Column("minimum_confidence", postgresql.JSONB(), nullable=False),
        sa.Column("allow_stale", sa.Boolean(), nullable=False),
        sa.Column("allow_conflicted", sa.Boolean(), nullable=False),
        sa.Column("critical_requires_escalation", sa.Boolean(), nullable=False),
        sa.Column("include_evidence_excerpt", sa.Boolean(), nullable=False),
        sa.Column("include_internal_location", sa.Boolean(), nullable=False),
        sa.Column("max_context_tokens", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_helpdesk_policies_profile", "helpdesk_policies", ["consumer_profile"])
    op.create_index("ix_helpdesk_policies_active", "helpdesk_policies", ["active"])

    op.create_table(
        "helpdesk_interactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("consumer", sa.String(length=320), nullable=False),
        sa.Column("consumer_profile", sa.String(length=40), nullable=False),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("question_redacted", sa.Text(), nullable=True),
        sa.Column("request_context", postgresql.JSONB(), nullable=False),
        sa.Column("resolved_context", postgresql.JSONB(), nullable=False),
        sa.Column("policy_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("knowledge_refs", postgresql.JSONB(), nullable=False),
        sa.Column("answerability", sa.String(length=30), nullable=False),
        sa.Column("recommended_action", sa.String(length=30), nullable=False),
        sa.Column("retrieval_version", sa.String(length=30), nullable=False),
        sa.Column("knowledge_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("budget", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_helpdesk_interactions_consumer", "helpdesk_interactions", ["consumer"])
    op.create_index("ix_helpdesk_interactions_profile", "helpdesk_interactions", ["consumer_profile"])
    op.create_index("ix_helpdesk_interactions_question", "helpdesk_interactions", ["question_hash"])
    op.create_index("ix_helpdesk_interactions_answerability", "helpdesk_interactions", ["answerability"])
    op.create_index("ix_helpdesk_interactions_action", "helpdesk_interactions", ["recommended_action"])
    op.create_index("ix_helpdesk_interactions_created", "helpdesk_interactions", ["created_at"])

    op.create_table(
        "helpdesk_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("interaction_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=30), nullable=False),
        sa.Column("helpful_atom_ids", postgresql.JSONB(), nullable=False),
        sa.Column("misleading_atom_ids", postgresql.JSONB(), nullable=False),
        sa.Column("missing_information", sa.Text(), nullable=True),
        sa.Column("correction", sa.Text(), nullable=True),
        sa.Column("ticket_reference", sa.String(length=300), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["interaction_id"], ["helpdesk_interactions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("interaction_id", "idempotency_key"),
    )
    op.create_index("ix_helpdesk_feedback_interaction", "helpdesk_feedback", ["interaction_id"])
    op.create_index("ix_helpdesk_feedback_outcome", "helpdesk_feedback", ["outcome"])
    op.create_index("ix_helpdesk_feedback_created", "helpdesk_feedback", ["created_at"])

    op.create_table(
        "evidence_freshness",
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source_head_commit", sa.String(length=100), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("evidence_id"),
    )
    op.create_index("ix_evidence_freshness_status", "evidence_freshness", ["status"])

    # Defaults pragmáticos: Direct usa canônico + provisório observado; Copilots podem
    # investigar o espaço de discovery, sempre preservando os rótulos.
    op.execute(
        """
        insert into helpdesk_policies
            (id, name, consumer_profile, scope_type, selector, allowed_statuses,
             minimum_confidence, allow_stale, allow_conflicted,
             critical_requires_escalation, include_evidence_excerpt,
             include_internal_location, max_context_tokens, active, detail,
             created_by, created_at, updated_at)
        values
            (gen_random_uuid(), 'Help Desk Direct — padrão', 'helpdesk_direct',
             'global', null, '["CANONICAL", "PROVISIONAL"]'::jsonb,
             '{"PROVISIONAL": 0.60}'::jsonb, false, false, true, false, false,
             8000, true, '{}'::jsonb, 'system:migration', now(), now()),
            (gen_random_uuid(), 'Help Desk Copilot N1 — padrão', 'helpdesk_copilot_n1',
             'global', null,
             '["CANONICAL", "PROVISIONAL", "NEEDS_HUMAN_REVIEW", "CANDIDATE", "CORROBORATING", "IN_REVIEW", "DECISION_PENDING", "CONFLICTED", "LEGACY_BUG"]'::jsonb,
             '{}'::jsonb, true, true, true, false, false, 10000, true,
             '{}'::jsonb, 'system:migration', now(), now()),
            (gen_random_uuid(), 'Help Desk Copilot N2 — padrão', 'helpdesk_copilot_n2',
             'global', null,
             '["CANONICAL", "PROVISIONAL", "NEEDS_HUMAN_REVIEW", "CANDIDATE", "CORROBORATING", "IN_REVIEW", "DECISION_PENDING", "CONFLICTED", "LEGACY_BUG"]'::jsonb,
             '{}'::jsonb, true, true, true, false, true, 14000, true,
             '{}'::jsonb, 'system:migration', now(), now()),
            (gen_random_uuid(), 'Help Desk Copilot N3 — padrão', 'helpdesk_copilot_n3',
             'global', null,
             '["CANONICAL", "PROVISIONAL", "NEEDS_HUMAN_REVIEW", "CANDIDATE", "CORROBORATING", "IN_REVIEW", "DECISION_PENDING", "CONFLICTED", "LEGACY_BUG"]'::jsonb,
             '{}'::jsonb, true, true, true, true, true, 20000, true,
             '{}'::jsonb, 'system:migration', now(), now())
        """
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_freshness_status", table_name="evidence_freshness")
    op.drop_table("evidence_freshness")
    op.drop_index("ix_helpdesk_feedback_created", table_name="helpdesk_feedback")
    op.drop_index("ix_helpdesk_feedback_outcome", table_name="helpdesk_feedback")
    op.drop_index("ix_helpdesk_feedback_interaction", table_name="helpdesk_feedback")
    op.drop_table("helpdesk_feedback")
    op.drop_index("ix_helpdesk_interactions_created", table_name="helpdesk_interactions")
    op.drop_index("ix_helpdesk_interactions_action", table_name="helpdesk_interactions")
    op.drop_index("ix_helpdesk_interactions_answerability", table_name="helpdesk_interactions")
    op.drop_index("ix_helpdesk_interactions_question", table_name="helpdesk_interactions")
    op.drop_index("ix_helpdesk_interactions_profile", table_name="helpdesk_interactions")
    op.drop_index("ix_helpdesk_interactions_consumer", table_name="helpdesk_interactions")
    op.drop_table("helpdesk_interactions")
    op.drop_index("ix_helpdesk_policies_active", table_name="helpdesk_policies")
    op.drop_index("ix_helpdesk_policies_profile", table_name="helpdesk_policies")
    op.drop_table("helpdesk_policies")
