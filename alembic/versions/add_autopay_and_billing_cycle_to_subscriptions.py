"""add autopay and billing cycle to subscriptions and payment transactions

Revision ID: add_autopay_billing_01
Revises: add_is_price_drop_01
Create Date: 2026-10-17 17:20:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_autopay_billing_01'
down_revision = 'add_is_price_drop_01'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Subscriptions columns
    sub_cols = [col['name'] for col in inspector.get_columns('subscriptions')]
    if 'auto_renew' not in sub_cols:
        op.add_column('subscriptions', sa.Column('auto_renew', sa.Boolean(), server_default='false', nullable=False))
    if 'billing_cycle' not in sub_cols:
        op.add_column('subscriptions', sa.Column('billing_cycle', sa.String(20), server_default='monthly', nullable=True))

    # Payment transactions columns
    tx_cols = [col['name'] for col in inspector.get_columns('payment_transactions')]
    if 'is_autopay' not in tx_cols:
        op.add_column('payment_transactions', sa.Column('is_autopay', sa.Boolean(), server_default='false', nullable=False))

def downgrade() -> None:
    pass
