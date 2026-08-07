"""add delivery pricing fields

Revision ID: d98e76a5b4c3
Revises: fa4445bf1363
Create Date: 2026-08-01 16:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd98e76a5b4c3'
down_revision = 'fa4445bf1363'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('shop_settings')]

    if 'base_delivery_charge' not in columns:
        op.add_column('shop_settings', sa.Column('base_delivery_charge', sa.Float(), nullable=False, server_default='0.0'))
    if 'base_delivery_distance' not in columns:
        op.add_column('shop_settings', sa.Column('base_delivery_distance', sa.Float(), nullable=False, server_default='0.0'))
    if 'extra_delivery_distance_step' not in columns:
        op.add_column('shop_settings', sa.Column('extra_delivery_distance_step', sa.Float(), nullable=False, server_default='1.0'))
    if 'extra_delivery_charge_per_step' not in columns:
        op.add_column('shop_settings', sa.Column('extra_delivery_charge_per_step', sa.Float(), nullable=False, server_default='0.0'))


def downgrade() -> None:
    op.drop_column('shop_settings', 'extra_delivery_charge_per_step')
    op.drop_column('shop_settings', 'extra_delivery_distance_step')
    op.drop_column('shop_settings', 'base_delivery_distance')
    op.drop_column('shop_settings', 'base_delivery_charge')
