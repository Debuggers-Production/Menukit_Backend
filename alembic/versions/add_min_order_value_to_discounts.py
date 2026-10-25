"""add min_order_value and max_discount_amount to discounts

Revision ID: add_min_order_value_01
Revises: add_autopay_billing_01
Create Date: 2026-10-20 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_min_order_value_01'
down_revision = 'add_autopay_billing_01'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    disc_cols = [col['name'] for col in inspector.get_columns('discounts')]
    if 'min_order_value' not in disc_cols:
        op.add_column('discounts', sa.Column('min_order_value', sa.Numeric(10, 2), nullable=True))
    if 'max_discount_amount' not in disc_cols:
        op.add_column('discounts', sa.Column('max_discount_amount', sa.Numeric(10, 2), nullable=True))

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    disc_cols = [col['name'] for col in inspector.get_columns('discounts')]
    if 'max_discount_amount' in disc_cols:
        op.drop_column('discounts', 'max_discount_amount')
    if 'min_order_value' in disc_cols:
        op.drop_column('discounts', 'min_order_value')
