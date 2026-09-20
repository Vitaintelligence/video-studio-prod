"""create generations table

Revision ID: 0001
Revises:
Create Date: 2026-09-20
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "generations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True, unique=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("pipeline", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_stage", sa.String(64), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_seconds_requested", sa.Integer(), nullable=False),
        sa.Column("aspect_ratio", sa.String(8), nullable=False),
        sa.Column("style", sa.String(64), nullable=True),
        sa.Column("voice_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("captions_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("quality_profile", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("project_path", sa.String(512), nullable=True),
        sa.Column("output_storage_key", sa.String(512), nullable=True),
        sa.Column("output_url", sa.Text(), nullable=True),
        sa.Column("thumbnail_storage_key", sa.String(512), nullable=True),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("actual_cost_usd", sa.Float(), nullable=True),
        sa.Column("runtime_provider", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", json_type, nullable=False),
    )
    op.create_index("ix_generations_user_created", "generations", ["user_id", "created_at"])
    op.create_index("ix_generations_status_created", "generations", ["status", "created_at"])
    op.create_index("ix_generations_created_at", "generations", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_generations_created_at", table_name="generations")
    op.drop_index("ix_generations_status_created", table_name="generations")
    op.drop_index("ix_generations_user_created", table_name="generations")
    op.drop_table("generations")
