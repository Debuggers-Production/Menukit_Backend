"""add max_order_value to discounts

Revision ID: add_max_order_value_01
Revises: add_min_order_value_01
Create Date: 2026-10-25 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_max_order_value_01'
down_revision = 'add_min_order_value_01'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    disc_cols = [col['name'] for col in inspector.get_columns('discounts')]
    if 'max_order_value' not in disc_cols:
        op.add_column('discounts', sa.Column('max_order_value', sa.Numeric(10, 2), nullable=True))

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    disc_cols = [col['name'] for col in inspector.get_columns('discounts')]
    if 'max_order_value' in disc_cols:
        op.drop_column('discounts', 'max_order_value')
