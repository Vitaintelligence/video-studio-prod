"""projects, assets, and edit fields on generations

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_user_updated", "projects", ["user_id", "updated_at"])
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assets_user_project", "assets", ["user_id", "project_id"])
    with op.batch_alter_table("generations") as b:
        b.add_column(sa.Column("kind", sa.String(16), nullable=False, server_default="generation"))
        b.add_column(sa.Column("project_id", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("parent_id", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("revision_number", sa.Integer(), nullable=True))
        b.add_column(sa.Column("platform", sa.String(16), nullable=True))
        b.add_column(sa.Column("variant_strategy", sa.String(32), nullable=True))
        b.add_column(sa.Column("variant_label", sa.String(64), nullable=True))
    op.create_index("ix_generations_project", "generations", ["project_id", "created_at"])
    op.create_index("ix_generations_parent", "generations", ["parent_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_generations_parent", table_name="generations")
    op.drop_index("ix_generations_project", table_name="generations")
    with op.batch_alter_table("generations") as b:
        for col in ("variant_label", "variant_strategy", "platform", "revision_number", "parent_id", "project_id", "kind"):
            b.drop_column(col)
    op.drop_index("ix_assets_user_project", table_name="assets")
    op.drop_table("assets")
    op.drop_index("ix_projects_user_updated", table_name="projects")
    op.drop_table("projects")
