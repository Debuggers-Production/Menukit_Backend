"""add_discounts_table

Revision ID: a1b2c3d4e5f6
Revises: 0f61042bdb50
Create Date: 2026-06-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0f61042bdb50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'discounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('shop_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('shops.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('discount_type', sa.String(20), server_default='percentage', nullable=False),
        sa.Column('discount_value', sa.Numeric(10, 2), nullable=False),
        sa.Column('applies_to', sa.String(20), server_default='all', nullable=False),
        sa.Column('target_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_discounts_shop_id', 'discounts', ['shop_id'])


def downgrade() -> None:
    op.drop_index('ix_discounts_shop_id', table_name='discounts')
    op.drop_table('discounts')
