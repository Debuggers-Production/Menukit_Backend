"""add subscription modules

Revision ID: f7a8b9c0d1e2
Revises: e6d9de35afa8
Create Date: 2026-08-07 10:06:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

# revision identifiers, used by Alembic.
revision = 'f7a8b9c0d1e2'
down_revision = 'e6d9de35afa8'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Handle subscriptions table
    sub_cols = [col['name'] for col in inspector.get_columns('subscriptions')]
    if 'active_modules' not in sub_cols:
        op.add_column('subscriptions', sa.Column('active_modules', sa.JSON(), nullable=True))
    if 'module_expirations' not in sub_cols:
        op.add_column('subscriptions', sa.Column('module_expirations', sa.JSON(), nullable=True))
        
    # Handle payment_transactions table
    pt_cols = [col['name'] for col in inspector.get_columns('payment_transactions')]
    if 'is_all_access' not in pt_cols:
        op.add_column('payment_transactions', sa.Column('is_all_access', sa.Boolean(), server_default='false', nullable=False))
    if 'purchased_modules' not in pt_cols:
        op.add_column('payment_transactions', sa.Column('purchased_modules', sa.JSON(), nullable=True))
    if 'billing_cycle' not in pt_cols:
        op.add_column('payment_transactions', sa.Column('billing_cycle', sa.String(length=20), server_default='monthly', nullable=True))


def downgrade() -> None:
    pass
