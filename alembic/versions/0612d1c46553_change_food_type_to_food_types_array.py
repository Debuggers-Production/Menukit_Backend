"""change food type to food types array

Revision ID: 0612d1c46553
Revises: 2e9d12cce89b
Create Date: 2026-06-08 09:30:16.517362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0612d1c46553'
down_revision: Union[str, None] = '2e9d12cce89b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('menu_items', 'food_type', new_column_name='food_types')
    op.execute("ALTER TABLE menu_items ALTER COLUMN food_types TYPE JSONB USING jsonb_build_array(food_types)")


def downgrade() -> None:
    op.execute("ALTER TABLE menu_items ALTER COLUMN food_types TYPE VARCHAR(10) USING food_types->>0")
    op.alter_column('menu_items', 'food_types', new_column_name='food_type')
