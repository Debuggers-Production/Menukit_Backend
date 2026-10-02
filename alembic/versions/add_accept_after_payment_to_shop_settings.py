"""add accept_after_payment to shop_settings

Revision ID: add_accept_after_pay_01
Revises: bd0c4cda5434
Create Date: 2026-10-02 16:47:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_accept_after_pay_01'
down_revision = 'bd0c4cda5434'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    ss_cols = [col['name'] for col in inspector.get_columns('shop_settings')]
    
    if 'accept_after_payment' not in ss_cols:
        op.add_column('shop_settings', sa.Column('accept_after_payment', sa.Boolean(), server_default='false', nullable=False))

def downgrade() -> None:
    pass
