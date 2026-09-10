"""Add customer discount codes and hide discovery badge

Revision ID: e1f2a3b4c5d6
Revises: cd14f47af018
Create Date: 2026-09-09 20:10:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'cd14f47af018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add hide_discovery_badge to shop_settings
    op.add_column(
        'shop_settings',
        sa.Column('hide_discovery_badge', sa.Boolean(), server_default=sa.text('false'), nullable=False)
    )

    # 1b. Add code to discounts
    op.add_column(
        'discounts',
        sa.Column('code', sa.String(length=50), nullable=True)
    )
    op.create_index(op.f('ix_discounts_code'), 'discounts', ['code'], unique=False)

    # 2. Create customer_discount_codes table
    op.create_table(
        'customer_discount_codes',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('discount_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('shop_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('customer_identifier', sa.String(length=100), nullable=False),
        sa.Column('code', sa.String(length=100), nullable=False),
        sa.Column('is_redeemed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('redeemed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['discount_id'], ['discounts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['shop_id'], ['shops.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_customer_discount_codes_discount_id'), 'customer_discount_codes', ['discount_id'], unique=False)
    op.create_index(op.f('ix_customer_discount_codes_shop_id'), 'customer_discount_codes', ['shop_id'], unique=False)
    op.create_index(op.f('ix_customer_discount_codes_customer_id'), 'customer_discount_codes', ['customer_id'], unique=False)
    op.create_index(op.f('ix_customer_discount_codes_customer_identifier'), 'customer_discount_codes', ['customer_identifier'], unique=False)
    op.create_index(op.f('ix_customer_discount_codes_code'), 'customer_discount_codes', ['code'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_discounts_code'), table_name='discounts')
    op.drop_column('discounts', 'code')
    op.drop_index(op.f('ix_customer_discount_codes_code'), table_name='customer_discount_codes')
    op.drop_index(op.f('ix_customer_discount_codes_customer_identifier'), table_name='customer_discount_codes')
    op.drop_index(op.f('ix_customer_discount_codes_customer_id'), table_name='customer_discount_codes')
    op.drop_index(op.f('ix_customer_discount_codes_shop_id'), table_name='customer_discount_codes')
    op.drop_index(op.f('ix_customer_discount_codes_discount_id'), table_name='customer_discount_codes')
    op.drop_table('customer_discount_codes')
    op.drop_column('shop_settings', 'hide_discovery_badge')
