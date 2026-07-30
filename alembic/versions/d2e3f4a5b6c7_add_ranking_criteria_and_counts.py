"""add_ranking_criteria_and_counts

Revision ID: d2e3f4a5b6c7
Revises: c1e2f3a4b5d6
Create Date: 2026-07-25 18:41:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1e2f3a4b5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('contests', sa.Column('ranking_criterion', sa.String(length=20), server_default='likes', nullable=False))
    op.add_column('contests', sa.Column('min_comments', sa.Integer(), server_default='0', nullable=False))
    op.add_column('contests', sa.Column('min_shares', sa.Integer(), server_default='0', nullable=False))
    
    op.add_column('contest_participations', sa.Column('comments_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('contest_participations', sa.Column('shares_count', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('contest_participations', 'shares_count')
    op.drop_column('contest_participations', 'comments_count')
    
    op.drop_column('contests', 'min_shares')
    op.drop_column('contests', 'min_comments')
    op.drop_column('contests', 'ranking_criterion')
