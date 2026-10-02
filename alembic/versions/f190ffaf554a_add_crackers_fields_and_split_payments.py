"""add_crackers_fields_and_split_payments

Revision ID: f190ffaf554a
Revises: a1c2e3f4b5a6
Create Date: 2026-10-01 16:32:49.983551

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f190ffaf554a'
down_revision: Union[str, None] = 'a1c2e3f4b5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Menu Items Table
    menu_item_cols = [col['name'] for col in inspector.get_columns('menu_items')]
    if 'serial_number' not in menu_item_cols:
        op.add_column('menu_items', sa.Column('serial_number', sa.String(length=100), nullable=True))
    if 'multiplier' not in menu_item_cols:
        op.add_column('menu_items', sa.Column('multiplier', sa.Integer(), server_default='1', nullable=True))
    if 'wholesale_price' not in menu_item_cols:
        op.add_column('menu_items', sa.Column('wholesale_price', sa.Numeric(precision=10, scale=2), nullable=True))
    if 'other_price' not in menu_item_cols:
        op.add_column('menu_items', sa.Column('other_price', sa.Numeric(precision=10, scale=2), nullable=True))
    if 'is_public_visible' not in menu_item_cols:
        op.add_column('menu_items', sa.Column('is_public_visible', sa.Boolean(), server_default='true', nullable=False))

    # 2. Orders Table
    order_cols = [col['name'] for col in inspector.get_columns('orders')]
    if 'split_payments' not in order_cols:
        op.add_column('orders', sa.Column('split_payments', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    if 'price_tier' not in order_cols:
        op.add_column('orders', sa.Column('price_tier', sa.String(length=50), server_default='retail', nullable=True))

    # 3. Shop Settings Table
    ss_cols = [col['name'] for col in inspector.get_columns('shop_settings')]
    if 'max_delivery_distance' in ss_cols:
        try:
            op.alter_column('shop_settings', 'max_delivery_distance', server_default=sa.text('0.0'))
        except Exception:
            pass
    if 'dinein_tables_count' in ss_cols:
        try:
            op.alter_column('shop_settings', 'dinein_tables_count', server_default=sa.text('10'))
        except Exception:
            pass
    if 'gst_enabled' in ss_cols:
        try:
            op.alter_column('shop_settings', 'gst_enabled', server_default=sa.text('false'))
        except Exception:
            pass
    if 'cgst_rate' in ss_cols:
        try:
            op.alter_column('shop_settings', 'cgst_rate', server_default=sa.text('2.5'))
        except Exception:
            pass
    if 'sgst_rate' in ss_cols:
        try:
            op.alter_column('shop_settings', 'sgst_rate', server_default=sa.text('2.5'))
        except Exception:
            pass
    if 'inclusive_tax' in ss_cols:
        try:
            op.alter_column('shop_settings', 'inclusive_tax', server_default=sa.text('false'))
        except Exception:
            pass


def downgrade() -> None:
    pass
