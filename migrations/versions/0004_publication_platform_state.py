"""publication platform_state for multi-step uploads

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-25 03:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('publications', sa.Column('platform_state', sa.JSON(), nullable=False, server_default='{}'))


def downgrade() -> None:
    op.drop_column('publications', 'platform_state')
