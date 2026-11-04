"""add is_deleted and deleted_at to users and shops

Revision ID: add_is_deleted_01
Revises: add_is_taxable_01
Create Date: 2026-11-01 19:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_is_deleted_01'
down_revision = 'add_is_taxable_01'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_cols = [col['name'] for col in inspector.get_columns('users')]
    if 'is_deleted' not in user_cols:
        op.add_column(
            'users', 
            sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False)
        )
    if 'deleted_at' not in user_cols:
        op.add_column(
            'users', 
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True)
        )

    shop_cols = [col['name'] for col in inspector.get_columns('shops')]
    if 'is_deleted' not in shop_cols:
        op.add_column(
            'shops', 
            sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False)
        )
    if 'deleted_at' not in shop_cols:
        op.add_column(
            'shops', 
            sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True)
        )

def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    user_cols = [col['name'] for col in inspector.get_columns('users')]
    if 'is_deleted' in user_cols:
        op.drop_column('users', 'is_deleted')
    if 'deleted_at' in user_cols:
        op.drop_column('users', 'deleted_at')

    shop_cols = [col['name'] for col in inspector.get_columns('shops')]
    if 'is_deleted' in shop_cols:
        op.drop_column('shops', 'is_deleted')
    if 'deleted_at' in shop_cols:
        op.drop_column('shops', 'deleted_at')

