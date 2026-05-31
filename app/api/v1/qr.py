"""QR Code API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.core.deps import get_current_user
from app.schemas.qr_code import QRCodeResponse
from app.services.qr_service import QRService
from app.models.user import User

router = APIRouter(prefix="/qr", tags=["QR Code"])


@router.post("/generate", response_model=QRCodeResponse)
async def generate_qr(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate or regenerate a QR code for the user's shop."""
    service = QRService(db)
    qr = await service.generate_qr(user.id)
    return QRCodeResponse.model_validate(qr)


@router.get("/info", response_model=QRCodeResponse)
async def get_qr_info(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current QR code info for the user's shop."""
    service = QRService(db)
    qr = await service.get_qr(user.id)
    return QRCodeResponse.model_validate(qr)
