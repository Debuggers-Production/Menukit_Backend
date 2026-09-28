"""add user phone and phone_verified fields

Revision ID: fa5566bf1474
Revises: f8b9c0d1e2f3
Create Date: 2026-09-25 11:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'fa5566bf1474'
down_revision = 'f8b9c0d1e2f3'
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    users_cols = [col['name'] for col in inspector.get_columns('users')]
    
    if 'phone' not in users_cols:
        op.add_column('users', sa.Column('phone', sa.String(length=20), nullable=True))
        op.create_index('ix_users_phone', 'users', ['phone'], unique=False)
    if 'phone_verified' not in users_cols:
        op.add_column('users', sa.Column('phone_verified', sa.Boolean(), server_default='false', nullable=False))

def downgrade() -> None:
    op.drop_index('ix_users_phone', table_name='users')
    op.drop_column('users', 'phone_verified')
    op.drop_column('users', 'phone')
