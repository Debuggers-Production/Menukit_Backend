"""Upload API endpoints."""
import logging
import uuid

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user
from app.schemas.menu_item import MenuImageResponse
from app.services.upload_service import UploadService
from app.services.menu_service import MenuService
from app.models.user import User
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["Uploads"])


@router.post("/image")
async def upload_image(
    file: UploadFile = File(...),
    folder: str = Form("general"),
    item_id: str = Form(None),
    is_primary: bool = Form(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload an image (logo, banner, or food item)."""
    upload_service = UploadService()
    
    # Restrict folder names for security
    allowed_folders = {"logos", "banners", "items", "general"}
    if folder not in allowed_folders:
        folder = "general"
        
    result = await upload_service.upload_image(file, folder)

    logger.info(f"Generated URL: {result['image_url']}")
    logger.info(f"Generated Thumb: {result['thumbnail_url']}")
    
    # If item_id is provided, automatically attach to menu item
    if item_id and folder == "items":
        logger.info(f"Attaching image to menu item {item_id}")
        menu_service = MenuService(db)
        try:
            image = await menu_service.add_menu_image(
                item_id=uuid.UUID(item_id),
                image_url=result["image_url"],
                thumbnail_url=result["thumbnail_url"],
                is_primary=is_primary,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
            
        logger.info(f"Successfully attached image {image.id}")
        return {
            "url": result["image_url"],
            "thumbnail": result["thumbnail_url"],
            "image_record": MenuImageResponse(
                id=str(image.id),
                image_url=image.image_url,
                thumbnail_url=image.thumbnail_url,
                is_primary=image.is_primary,
                display_order=image.display_order
            )
        }
        
    return {
        "url": result["image_url"],
        "thumbnail": result["thumbnail_url"]
    }
