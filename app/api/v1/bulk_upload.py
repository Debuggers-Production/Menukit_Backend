"""Bulk Upload API endpoints."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.session import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.category import Category
from app.models.menu_item import MenuItem
from app.services.gemini_service import GeminiService
from app.services.shop_service import ShopService
from app.services.menu_service import MenuService

router = APIRouter(prefix="/bulk-upload", tags=["Bulk Upload"])

class ParsedItemResponse(BaseModel):
    category_name: str
    name: str
    description: Optional[str] = None
    price: float
    food_types: List[str]

class BulkImportItem(BaseModel):
    category_name: str
    name: str
    description: Optional[str] = None
    price: float
    food_types: List[str]

class BulkImportRequest(BaseModel):
    items: List[BulkImportItem]

class BulkImportResponse(BaseModel):
    message: str
    categories_created: int
    items_created: int


@router.post("/parse", response_model=List[ParsedItemResponse])
async def parse_menu_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    """Parse a menu PDF or Image using Gemini AI."""
    
    # Check mime type
    valid_types = ["application/pdf", "image/jpeg", "image/png", "image/webp"]
    if file.content_type not in valid_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a PDF or Image.")
    
    file_bytes = await file.read()
    
    gemini_service = GeminiService()
    try:
        items = await gemini_service.parse_menu_file(file_bytes, file.content_type)
        return items
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Parsing failed: {str(e)}")


@router.post("/confirm", response_model=BulkImportResponse)
async def confirm_bulk_import(
    request: BulkImportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Confirm and import the extracted menu items."""
    shop_service = ShopService(db)
    menu_service = MenuService(db)
    
    shop = await shop_service.get_shop_by_user(user.id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
        
    # Get existing categories
    categories = await menu_service.get_categories(shop.id)
    category_map = {c.name.lower(): c.id for c in categories}
    
    categories_created = 0
    items_created = 0
    
    # Group items by category to minimize category creation logic
    grouped_items = {}
    for item in request.items:
        if item.category_name not in grouped_items:
            grouped_items[item.category_name] = []
        grouped_items[item.category_name].append(item)
        
    # Get highest display order for new categories
    max_cat_order = max([c.display_order for c in categories]) if categories else 0
        
    for cat_name, items in grouped_items.items():
        cat_key = cat_name.lower()
        if cat_key not in category_map:
            # Create category
            max_cat_order += 1
            new_cat = await menu_service.create_category(
                user.id, 
                {"name": cat_name, "display_order": max_cat_order, "is_active": True}
            )
            category_map[cat_key] = new_cat.id
            categories_created += 1
            
        cat_id = category_map[cat_key]
        
        # Get existing items in this category to set display order
        existing_items = await menu_service.get_menu_items(shop.id, category_id=cat_id)
        max_item_order = max([i.display_order for i in existing_items]) if existing_items else 0
        
        for item in items:
            max_item_order += 1
            item_data = {
                "category_id": str(cat_id),
                "name": item.name,
                "description": item.description,
                "price": item.price,
                "food_types": item.food_types,
                "is_available": True,
                "is_bestseller": False,
                "is_highlighted": False,
                "allow_ice_preference": False,
                "display_order": max_item_order,
                "variants": [],
                "addons": []
            }
            await menu_service.create_menu_item(user.id, item_data)
            items_created += 1
            
    # Commit changes from services
    await db.commit()
            
    return BulkImportResponse(
        message="Menu items imported successfully",
        categories_created=categories_created,
        items_created=items_created
    )
