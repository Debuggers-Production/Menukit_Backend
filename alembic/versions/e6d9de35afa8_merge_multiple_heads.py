"""merge multiple heads

Revision ID: e6d9de35afa8
Revises: 46307d7e43ce, 9bbed6ef5601
Create Date: 2026-08-07 15:22:56.321121

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6d9de35afa8'
down_revision: Union[str, None] = ('46307d7e43ce', '9bbed6ef5601')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
