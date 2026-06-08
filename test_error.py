import asyncio
import httpx
from datetime import datetime, timedelta, timezone
from jose import jwt
import urllib.parse

# JWT settings from config
SECRET_KEY = "change-this-jwt-secret-key"
ALGORITHM = "HS256"

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=30)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def test():
    # 1. Create a fake user token. 
    # We don't even need a real user if the DB just checks user.id. 
    # Wait, get_current_user checks the user exists in DB. 
    # Let's get the first user from DB.
    from app.database.session import async_session_factory
    from app.models.user import User
    from sqlalchemy import select
    
    async with async_session_factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        if not user:
            print("No users found in DB")
            return
            
        token = create_access_token({"sub": str(user.id)})
        
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Get first menu item for this user's shop
    from app.services.shop_service import ShopService
    from app.services.menu_service import MenuService
    
    async with async_session_factory() as db:
        shop_service = ShopService(db)
        shop = await shop_service.get_shop_by_user(user.id)
        if not shop:
            print("No shop found")
            return
            
        menu_service = MenuService(db)
        items = await menu_service.get_menu_items(shop.id)
        if not items:
            print("No items found")
            return
            
        item_id = str(items[0].id)
        item_name = items[0].name
        print(f"Using item: {item_id} ({item_name})")
        
    # 3. Get image URLs
    async with httpx.AsyncClient() as client:
        # We need a URL to save. Let's just use a picsum url
        url_to_save = "https://picsum.photos/seed/123/800/600"
        
        # 4. Save image
        resp = await client.post(
            f"http://127.0.0.1:8000/api/v1/menu-items/{item_id}/save-image-url",
            json={"url": url_to_save},
            headers=headers,
            timeout=30.0
        )
        print("Status:", resp.status_code)
        print("Response:", resp.text)

asyncio.run(test())
