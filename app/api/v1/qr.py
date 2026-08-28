"""QR Code API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user, get_current_shop_context
from app.schemas.qr_code import QRCodeResponse, QRCodeStyleUpdate
from app.services.qr_service import QRService
from app.models.user import User
from app.models.shop import Shop

router = APIRouter(prefix="/qr", tags=["QR Code"])


@router.post("/generate", response_model=QRCodeResponse)
async def generate_qr(
    user: User = Depends(get_current_user),
    shop: Shop = Depends(get_current_shop_context),
    db: AsyncSession = Depends(get_db),
):
    """Generate or regenerate a QR code for the brand."""
    service = QRService(db)
    owner_user_id = shop.user_id if shop else user.id
    qr = await service.generate_qr(shop.id if shop else user.id, owner_user_id)
    return QRCodeResponse.model_validate(qr)


@router.get("/info", response_model=QRCodeResponse)
async def get_qr_info(
    user: User = Depends(get_current_user),
    shop: Shop = Depends(get_current_shop_context),
    db: AsyncSession = Depends(get_db),
):
    """Get the current QR code info for the brand."""
    service = QRService(db)
    owner_user_id = shop.user_id if shop else user.id
    qr = await service.get_qr(owner_user_id, shop_id=shop.id if shop else None)
    return QRCodeResponse.model_validate(qr)


@router.put("/style", response_model=QRCodeResponse)
async def update_qr_style(
    style_data: QRCodeStyleUpdate,
    user: User = Depends(get_current_user),
    shop: Shop = Depends(get_current_shop_context),
    db: AsyncSession = Depends(get_db),
):
    """Update style preferences for the QR code."""
    service = QRService(db)
    owner_user_id = shop.user_id if shop else user.id
    qr = await service.update_qr_style(owner_user_id, style_data)
    await db.commit()
    return QRCodeResponse.model_validate(qr)
