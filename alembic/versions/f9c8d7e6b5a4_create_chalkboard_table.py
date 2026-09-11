"""create chalkboard table

Revision ID: f9c8d7e6b5a4
Revises: 976b1034a671
Create Date: 2026-09-11 10:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f9c8d7e6b5a4'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if 'chalkboards' not in tables:
        op.create_table(
            'chalkboards',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column('shop_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('shops.id', ondelete='CASCADE'), unique=True, nullable=False),
            sa.Column('is_enabled', sa.Boolean(), default=True, server_default=sa.text('true'), nullable=False),
            sa.Column('title', sa.String(100), nullable=True),
            sa.Column('message', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        )
        op.create_index('ix_chalkboards_shop_id', 'chalkboards', ['shop_id'], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if 'chalkboards' in tables:
        op.drop_table('chalkboards')
