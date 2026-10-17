"""add is_price_drop to discounts

Revision ID: add_is_price_drop_01
Revises: add_accept_after_pay_01
Create Date: 2026-10-17 11:55:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_is_price_drop_01'
down_revision = 'add_accept_after_pay_01'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    d_cols = [col['name'] for col in inspector.get_columns('discounts')]
    
    if 'is_price_drop' not in d_cols:
        op.add_column('discounts', sa.Column('is_price_drop', sa.Boolean(), server_default='false', nullable=False))

def downgrade() -> None:
    pass
