import re

with open(r'd:\Projects\Menukit\Menukit_Backend\alembic\versions\cd14f47af018_add_menu_catalogs_and_branch_overrides.py', 'r') as f:
    content = f.read()

# Make columns initially nullable
content = content.replace(
    "op.add_column('categories', sa.Column('menu_catalog_id', sa.UUID(), nullable=False))",
    "op.add_column('categories', sa.Column('menu_catalog_id', sa.UUID(), nullable=True))"
)
content = content.replace(
    "op.add_column('discounts', sa.Column('menu_catalog_id', sa.UUID(), nullable=False))",
    "op.add_column('discounts', sa.Column('menu_catalog_id', sa.UUID(), nullable=True))"
)
content = content.replace(
    "op.add_column('menu_items', sa.Column('menu_catalog_id', sa.UUID(), nullable=False))",
    "op.add_column('menu_items', sa.Column('menu_catalog_id', sa.UUID(), nullable=True))"
)

# Insert data migration logic right after the shops add_column
data_migration = """
    op.execute('''
        INSERT INTO menu_catalogs (id, user_id, name, created_at, updated_at)
        SELECT gen_random_uuid(), user_id, name || ' Menu', NOW(), NOW() FROM shops;
    ''')
    op.execute('''
        UPDATE shops SET menu_catalog_id = mc.id
        FROM menu_catalogs mc WHERE mc.name = shops.name || ' Menu' AND mc.user_id = shops.user_id;
    ''')
    op.execute('''
        UPDATE categories SET menu_catalog_id = s.menu_catalog_id
        FROM shops s WHERE categories.shop_id = s.id;
    ''')
    op.execute('''
        UPDATE menu_items SET menu_catalog_id = s.menu_catalog_id
        FROM shops s WHERE menu_items.shop_id = s.id;
    ''')
    op.execute('''
        UPDATE discounts SET menu_catalog_id = s.menu_catalog_id
        FROM shops s WHERE discounts.shop_id = s.id;
    ''')
    
    op.alter_column('categories', 'menu_catalog_id', nullable=False)
    op.alter_column('menu_items', 'menu_catalog_id', nullable=False)
    op.alter_column('discounts', 'menu_catalog_id', nullable=False)
"""

content = content.replace(
    "op.add_column('shops', sa.Column('menu_catalog_id', sa.UUID(), nullable=True))",
    "op.add_column('shops', sa.Column('menu_catalog_id', sa.UUID(), nullable=True))\n" + data_migration
)

with open(r'd:\Projects\Menukit\Menukit_Backend\alembic\versions\cd14f47af018_add_menu_catalogs_and_branch_overrides.py', 'w') as f:
    f.write(content)
