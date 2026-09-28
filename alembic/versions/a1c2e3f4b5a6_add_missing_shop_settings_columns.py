"""add missing shop_settings columns and merge heads

Revision ID: a1c2e3f4b5a6
Revises: bc4c5b81aa3d, fa5566bf1474
Create Date: 2026-09-28 15:36:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1c2e3f4b5a6'
down_revision: Union[str, Sequence[str], None] = ('bc4c5b81aa3d', 'fa5566bf1474')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [col['name'] for col in inspector.get_columns('shop_settings')]

    if 'dinein_tables_count' not in cols:
        op.add_column(
            'shop_settings',
            sa.Column('dinein_tables_count', sa.Integer(), server_default='10', nullable=False)
        )
    if 'online_payments_dinein_enabled' not in cols:
        op.add_column(
            'shop_settings',
            sa.Column('online_payments_dinein_enabled', sa.Boolean(), server_default='true', nullable=False)
        )
    if 'online_payments_takeaway_enabled' not in cols:
        op.add_column(
            'shop_settings',
            sa.Column('online_payments_takeaway_enabled', sa.Boolean(), server_default='true', nullable=False)
        )
    if 'online_payments_delivery_enabled' not in cols:
        op.add_column(
            'shop_settings',
            sa.Column('online_payments_delivery_enabled', sa.Boolean(), server_default='true', nullable=False)
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [col['name'] for col in inspector.get_columns('shop_settings')]

    if 'online_payments_delivery_enabled' in cols:
        op.drop_column('shop_settings', 'online_payments_delivery_enabled')
    if 'online_payments_takeaway_enabled' in cols:
        op.drop_column('shop_settings', 'online_payments_takeaway_enabled')
    if 'online_payments_dinein_enabled' in cols:
        op.drop_column('shop_settings', 'online_payments_dinein_enabled')
    if 'dinein_tables_count' in cols:
        op.drop_column('shop_settings', 'dinein_tables_count')
