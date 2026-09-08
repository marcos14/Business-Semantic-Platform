"""execução remota do harness: agentes, tarefas, git_url da source e executed_by do run

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-09-07 20:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "b4c5d6e7f8a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("git_url", sa.String(length=500), nullable=True))
    op.add_column(
        "discovery_runs", sa.Column("executed_by", sa.String(length=320), nullable=True)
    )

    op.create_table(
        "harness_agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("client_id", sa.String(length=80), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("host", sa.String(length=200), nullable=True),
        sa.Column("agent_version", sa.String(length=40), nullable=True),
        sa.Column("cli_version", sa.String(length=100), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limited_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limit_detail", sa.Text(), nullable=True),
        sa.Column("tasks_done", sa.Integer(), nullable=False),
        sa.Column("tasks_failed", sa.Integer(), nullable=False),
        sa.Column("cost_usd_total", sa.Float(), nullable=False),
        sa.Column("cost_usd_today", sa.Float(), nullable=False),
        sa.Column("cost_day", sa.Date(), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_harness_agents_client_id", "harness_agents", ["client_id"], unique=True)
    op.create_index("ix_harness_agents_user_id", "harness_agents", ["user_id"])
    op.create_index("ix_harness_agents_active", "harness_agents", ["active"])

    op.create_table(
        "harness_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("packet", postgresql.JSONB(), nullable=False),
        sa.Column("lease_agent_id", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("log_text", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("executed_by", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["discovery_runs.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["lease_agent_id"], ["harness_agents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_harness_tasks_run_id", "harness_tasks", ["run_id"])
    op.create_index("ix_harness_tasks_source_id", "harness_tasks", ["source_id"])
    op.create_index("ix_harness_tasks_status", "harness_tasks", ["status"])
    op.create_index("ix_harness_tasks_lease_agent_id", "harness_tasks", ["lease_agent_id"])


def downgrade() -> None:
    op.drop_index("ix_harness_tasks_lease_agent_id", table_name="harness_tasks")
    op.drop_index("ix_harness_tasks_status", table_name="harness_tasks")
    op.drop_index("ix_harness_tasks_source_id", table_name="harness_tasks")
    op.drop_index("ix_harness_tasks_run_id", table_name="harness_tasks")
    op.drop_table("harness_tasks")
    op.drop_index("ix_harness_agents_active", table_name="harness_agents")
    op.drop_index("ix_harness_agents_user_id", table_name="harness_agents")
    op.drop_index("ix_harness_agents_client_id", table_name="harness_agents")
    op.drop_table("harness_agents")
    op.drop_column("discovery_runs", "executed_by")
    op.drop_column("sources", "git_url")
