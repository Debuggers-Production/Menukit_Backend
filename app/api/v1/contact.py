"""Contact and Customer Enquiry API endpoints."""

import logging
from typing import Optional
from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, HTTPException, BackgroundTasks, status

from app.services.email_service import email_service
from app.schemas.common import MessageResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["Contact & Enquiries"])


class ContactEnquiryRequest(BaseModel):
    name: str
    phone: str
    email: EmailStr
    country: str
    district: str
    state: Optional[str] = None
    business_name: Optional[str] = None
    enquiry_type: Optional[str] = "Demo Request"
    message: Optional[str] = None


@router.post("/enquiry", response_model=MessageResponse, status_code=status.HTTP_200_OK)
async def submit_contact_enquiry(
    data: ContactEnquiryRequest,
    background_tasks: BackgroundTasks,
):
    """
    Submit customer enquiry or demo booking request.
    Sends complete enquiry details to debuggerstechs@gmail.com.
    """
    clean_name = data.name.strip()
    clean_phone = data.phone.strip()
    clean_email = str(data.email).strip().lower()
    clean_country = data.country.strip()
    clean_district = data.district.strip()
    clean_state = (data.state or "").strip()
    clean_business = (data.business_name or "").strip()
    clean_type = (data.enquiry_type or "Demo Request").strip()
    clean_msg = (data.message or "").strip()

    if not clean_name or not clean_phone or not clean_district:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name, mobile number, and country/district location are required."
        )

    # Dispatch email notification in background
    background_tasks.add_task(
        email_service.send_contact_enquiry_email,
        name=clean_name,
        email=clean_email,
        phone=clean_phone,
        country=clean_country,
        district=clean_district,
        state=clean_state,
        business_name=clean_business,
        enquiry_type=clean_type,
        message=clean_msg,
        target_email="debuggerstechs@gmail.com",
    )

    return MessageResponse(
        message="Thank you! Your enquiry has been received. Our team will contact you shortly."
    )
