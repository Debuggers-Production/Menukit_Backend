"""add missing shop_settings columns

Revision ID: f8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-08-07 10:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f8b9c0d1e2f3'
down_revision = 'f7a8b9c0d1e2'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    ss_cols = [col['name'] for col in inspector.get_columns('shop_settings')]
    
    if 'delivery_enabled' not in ss_cols:
        op.add_column('shop_settings', sa.Column('delivery_enabled', sa.Boolean(), server_default='false', nullable=False))
    if 'base_delivery_charge' not in ss_cols:
        op.add_column('shop_settings', sa.Column('base_delivery_charge', sa.Float(), server_default='0.0', nullable=False))
    if 'base_delivery_distance' not in ss_cols:
        op.add_column('shop_settings', sa.Column('base_delivery_distance', sa.Float(), server_default='0.0', nullable=False))
    if 'extra_delivery_distance_step' not in ss_cols:
        op.add_column('shop_settings', sa.Column('extra_delivery_distance_step', sa.Float(), server_default='1.0', nullable=False))
    if 'extra_delivery_charge_per_step' not in ss_cols:
        op.add_column('shop_settings', sa.Column('extra_delivery_charge_per_step', sa.Float(), server_default='0.0', nullable=False))
    if 'takeaway_enabled' not in ss_cols:
        op.add_column('shop_settings', sa.Column('takeaway_enabled', sa.Boolean(), server_default='false', nullable=False))
    if 'dinein_enabled' not in ss_cols:
        op.add_column('shop_settings', sa.Column('dinein_enabled', sa.Boolean(), server_default='false', nullable=False))
    if 'auto_accept_orders' not in ss_cols:
        op.add_column('shop_settings', sa.Column('auto_accept_orders', sa.Boolean(), server_default='false', nullable=False))
    if 'cashfree_app_id' not in ss_cols:
        op.add_column('shop_settings', sa.Column('cashfree_app_id', sa.String(length=255), server_default='', nullable=False))
    if 'cashfree_secret_key' not in ss_cols:
        op.add_column('shop_settings', sa.Column('cashfree_secret_key', sa.String(length=255), server_default='', nullable=False))
    if 'cashfree_sandbox' not in ss_cols:
        op.add_column('shop_settings', sa.Column('cashfree_sandbox', sa.Boolean(), server_default='true', nullable=False))
    if 'upi_id' not in ss_cols:
        op.add_column('shop_settings', sa.Column('upi_id', sa.String(length=100), nullable=True))
    if 'online_payments_enabled' not in ss_cols:
        op.add_column('shop_settings', sa.Column('online_payments_enabled', sa.Boolean(), server_default='true', nullable=False))

def downgrade() -> None:
    pass
