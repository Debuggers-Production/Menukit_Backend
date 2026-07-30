"""add_contest_min_targets

Revision ID: c1e2f3a4b5d6
Revises: ba3b7c79d4b5
Create Date: 2026-07-25 18:28:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1e2f3a4b5d6'
down_revision: Union[str, None] = 'ba3b7c79d4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contests', sa.Column('min_participants', sa.Integer(), server_default='1', nullable=False))
    op.add_column('contests', sa.Column('min_likes', sa.Integer(), server_default='1', nullable=False))
    op.add_column('contests', sa.Column('cancel_reason', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('contests', 'cancel_reason')
    op.drop_column('contests', 'min_likes')
    op.drop_column('contests', 'min_participants')
