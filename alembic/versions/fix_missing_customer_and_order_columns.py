"""add missing columns for customers and orders

Revision ID: fix_cust_ord_cols_101
Revises: inv_998877665544
Create Date: 2026-08-07 10:52:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fix_cust_ord_cols_101'
down_revision = 'inv_998877665544'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Check customers table
    cust_cols = [col['name'] for col in inspector.get_columns('customers')]
    if 'delivery_address' not in cust_cols:
        op.add_column('customers', sa.Column('delivery_address', sa.String(length=500), nullable=True))
    if 'name' not in cust_cols:
        op.add_column('customers', sa.Column('name', sa.String(length=255), nullable=True))

    # Check orders table
    ord_cols = [col['name'] for col in inspector.get_columns('orders')]
    if 'razorpay_order_id' not in ord_cols:
        op.add_column('orders', sa.Column('razorpay_order_id', sa.String(length=255), nullable=True))
    if 'cashfree_order_id' not in ord_cols:
        op.add_column('orders', sa.Column('cashfree_order_id', sa.String(length=255), nullable=True))
    if 'payment_session_id' not in ord_cols:
        op.add_column('orders', sa.Column('payment_session_id', sa.String(length=255), nullable=True))
    if 'credits_rewarded' not in ord_cols:
        op.add_column('orders', sa.Column('credits_rewarded', sa.Boolean(), server_default='false', nullable=True))
    if 'delivery_address' not in ord_cols:
        op.add_column('orders', sa.Column('delivery_address', sa.String(), nullable=True))

def downgrade() -> None:
    pass
