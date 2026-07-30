"""Add contest models

Revision ID: 042856664086
Revises: 042856664085
Create Date: 2026-07-09 14:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '042856664086'
down_revision: Union[str, None] = '042856664085'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create contests table
    op.create_table('contests',
    sa.Column('shop_id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('reward_type', sa.String(length=50), nullable=False),
    sa.Column('reward_value', sa.String(length=255), nullable=True),
    sa.Column('contest_type', sa.String(length=50), nullable=False),
    sa.Column('applies_to', sa.String(length=20), nullable=False),
    sa.Column('target_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )

    # 2. Create contest_participations table
    op.create_table('contest_participations',
    sa.Column('contest_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('content_type', sa.String(length=50), nullable=False),
    sa.Column('text_content', sa.Text(), nullable=True),
    sa.Column('media_url', sa.String(length=1024), nullable=True),
    sa.Column('likes_count', sa.Integer(), nullable=False),
    sa.Column('time_remaining_seconds', sa.Integer(), nullable=False),
    sa.Column('is_timer_running', sa.Boolean(), nullable=False),
    sa.Column('timer_last_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_submitted', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['contest_id'], ['contests.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )

    # 3. Create contest_credits table
    op.create_table('contest_credits',
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('credits', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('customer_id')
    )

    # 4. Create contest_likes table
    op.create_table('contest_likes',
    sa.Column('participation_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['participation_id'], ['contest_participations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('contest_likes')
    op.drop_table('contest_credits')
    op.drop_table('contest_participations')
    op.drop_table('contests')
