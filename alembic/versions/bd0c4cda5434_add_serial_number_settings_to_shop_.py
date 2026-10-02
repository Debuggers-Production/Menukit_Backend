"""add serial_number settings to shop_settings

Revision ID: bd0c4cda5434
Revises: 9d2b06f94871
Create Date: 2026-10-01 23:28:09.759975

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bd0c4cda5434'
down_revision: Union[str, None] = '9d2b06f94871'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    ss_cols = [col['name'] for col in inspector.get_columns('shop_settings')]
    if 'serial_number_prefix' not in ss_cols:
        op.add_column('shop_settings', sa.Column('serial_number_prefix', sa.String(length=20), server_default='', nullable=True))
    if 'serial_number_digits' not in ss_cols:
        op.add_column('shop_settings', sa.Column('serial_number_digits', sa.Integer(), server_default='3', nullable=False))
    if 'auto_serial_number_enabled' not in ss_cols:
        op.add_column('shop_settings', sa.Column('auto_serial_number_enabled', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    pass
