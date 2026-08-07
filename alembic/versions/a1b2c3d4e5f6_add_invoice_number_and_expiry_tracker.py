"""add invoice_number and expiry notification tracking

Revision ID: inv_998877665544
Revises: f8b9c0d1e2f3
Create Date: 2026-08-07 10:47:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'inv_998877665544'
down_revision = 'f8b9c0d1e2f3'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    pt_cols = [col['name'] for col in inspector.get_columns('payment_transactions')]
    if 'invoice_number' not in pt_cols:
        op.add_column('payment_transactions', sa.Column('invoice_number', sa.String(length=100), nullable=True))
        op.create_index(op.f('ix_payment_transactions_invoice_number'), 'payment_transactions', ['invoice_number'], unique=False)
        
    sub_cols = [col['name'] for col in inspector.get_columns('subscriptions')]
    if 'last_expiry_notification_date' not in sub_cols:
        op.add_column('subscriptions', sa.Column('last_expiry_notification_date', sa.String(length=50), nullable=True))

def downgrade() -> None:
    pass
