"""add is_taxable to menu_items and order_items

Revision ID: add_is_taxable_01
Revises: add_max_order_value_01
Create Date: 2026-11-01 16:05:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_is_taxable_01'
down_revision = 'add_max_order_value_01'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    menu_item_cols = [col['name'] for col in inspector.get_columns('menu_items')]
    if 'is_taxable' not in menu_item_cols:
        op.add_column(
            'menu_items', 
            sa.Column('is_taxable', sa.Boolean(), server_default=sa.text('true'), nullable=False)
        )

    order_item_cols = [col['name'] for col in inspector.get_columns('order_items')]
    if 'is_taxable' not in order_item_cols:
        op.add_column(
            'order_items', 
            sa.Column('is_taxable', sa.Boolean(), server_default=sa.text('true'), nullable=False)
        )

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    menu_item_cols = [col['name'] for col in inspector.get_columns('menu_items')]
    if 'is_taxable' in menu_item_cols:
        op.drop_column('menu_items', 'is_taxable')

    order_item_cols = [col['name'] for col in inspector.get_columns('order_items')]
    if 'is_taxable' in order_item_cols:
        op.drop_column('order_items', 'is_taxable')

