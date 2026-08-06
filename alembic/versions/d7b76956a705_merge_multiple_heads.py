"""Merge multiple heads

Revision ID: d7b76956a705
Revises: d2e3f4a5b6c7, d98e76a5b4c3
Create Date: 2026-08-05 10:42:25.308440

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7b76956a705'
down_revision: Union[str, None] = ('d2e3f4a5b6c7', 'd98e76a5b4c3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
