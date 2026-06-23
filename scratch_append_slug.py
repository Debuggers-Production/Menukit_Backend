import os

FILE_PATH = r"d:\projects\menu_project\menukit_backend\app\api\v1\public.py"

new_func = '''
@shops_router.get("/by-slug/{slug}", response_model=ShopResponse)
async def get_shop_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Get shop details by slug for public SEO page."""
    from app.models.shop import Shop
    from sqlalchemy.orm import selectinload
    
    result = await db.execute(
        select(Shop)
        .options(
            selectinload(Shop.settings),
            selectinload(Shop.theme)
        )
        .where(Shop.slug == slug, Shop.is_active == True)
    )
    shop = result.scalars().first()
    
    if not shop:
        raise NotFoundException("Restaurant not found")
        
    return _shop_to_response(shop)
'''

with open(FILE_PATH, "a", encoding="utf-8") as f:
    f.write(new_func)
print("Appended get_shop_by_slug")
