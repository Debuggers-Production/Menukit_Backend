"""add wholesale_multiplier and other_multiplier to menu_items

Revision ID: 9d2b06f94871
Revises: f190ffaf554a
Create Date: 2026-10-01 17:22:10.257795

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d2b06f94871'
down_revision: Union[str, None] = 'f190ffaf554a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    menu_item_cols = [col['name'] for col in inspector.get_columns('menu_items')]
    if 'wholesale_multiplier' not in menu_item_cols:
        op.add_column('menu_items', sa.Column('wholesale_multiplier', sa.Integer(), server_default='1', nullable=True))
    if 'other_multiplier' not in menu_item_cols:
        op.add_column('menu_items', sa.Column('other_multiplier', sa.Integer(), server_default='1', nullable=True))


def downgrade() -> None:
    pass
