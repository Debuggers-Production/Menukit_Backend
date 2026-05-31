import asyncio
import uuid
from app.database.session import async_session_factory
from app.services.menu_service import MenuService
from app.models.menu_item import MenuItem
from app.models.menu_image import MenuImage
from sqlalchemy import select

async def simulate_menu_upload():
    async with async_session_factory() as db:
        service = MenuService(db)
        
        # 1. Get an existing menu item
        res = await db.execute(select(MenuItem).limit(1))
        item = res.scalar_one_or_none()
        if not item:
            print("No items found")
            return
            
        item_id = item.id
        print(f"Testing with item {item_id}")
        
        # Print current images
        res_imgs = await db.execute(select(MenuImage).where(MenuImage.menu_item_id == item_id))
        old_imgs = res_imgs.scalars().all()
        print(f"Old images: {[img.image_url for img in old_imgs]} (Primary: {[img.is_primary for img in old_imgs]})")
        
        # 2. Add a new image
        new_url = "http://89.167.72.254:9000/menuproductimages/items/new-test-menu-image.jpg"
        print("Uploading new image...")
        await service.add_menu_image(
            item_id=item_id,
            image_url=new_url,
            thumbnail_url=new_url,
            is_primary=True
        )
        
    # 3. Simulate new HTTP Request
    async with async_session_factory() as db2:
        res2 = await db2.execute(select(MenuImage).where(MenuImage.menu_item_id == item_id))
        new_imgs = res2.scalars().all()
        print(f"New images directly from DB: {[img.image_url for img in new_imgs]} (Primary: {[img.is_primary for img in new_imgs]})")
        
        service2 = MenuService(db2)
        item2 = await service2.get_menu_item(item_id)
        from app.api.v1.menu_items import _item_response
        resp = _item_response(item2)
        print(f"Response serialization output URL: {resp.image_url}")

if __name__ == "__main__":
    asyncio.run(simulate_menu_upload())
