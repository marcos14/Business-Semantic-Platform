"""machine identities for help desk consumers

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-07 16:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "helpdesk_client_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("client_id", sa.String(length=80), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("allowed_profiles", postgresql.JSONB(), nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("rate_window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_helpdesk_client_credentials_client_id",
        "helpdesk_client_credentials",
        ["client_id"],
        unique=True,
    )
    op.create_index(
        "ix_helpdesk_client_credentials_user_id",
        "helpdesk_client_credentials",
        ["user_id"],
    )
    op.create_index(
        "ix_helpdesk_client_credentials_active",
        "helpdesk_client_credentials",
        ["active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_helpdesk_client_credentials_active", table_name="helpdesk_client_credentials"
    )
    op.drop_index(
        "ix_helpdesk_client_credentials_user_id", table_name="helpdesk_client_credentials"
    )
    op.drop_index(
        "ix_helpdesk_client_credentials_client_id", table_name="helpdesk_client_credentials"
    )
    op.drop_table("helpdesk_client_credentials")
