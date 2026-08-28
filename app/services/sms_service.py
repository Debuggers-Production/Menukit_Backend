import httpx
import logging
from typing import Optional
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

class SMSService:
    """Service to handle SMS OTP via MSG91 Widget API."""

    def __init__(self):
        self.auth_key = settings.MSG91_AUTH_KEY
        self.widget_id = settings.MSG91_TEMPLATE_ID # Using TEMPLATE_ID config for WIDGET_ID
        self.mock_mode = settings.MOC_OTP
        self.base_url = "https://api.msg91.com/api/v5/widget"

    async def send_otp(self, mobile_number: str, country_code: str = "91", otp_length: int = 6) -> Optional[str]:
        """
        Send OTP to mobile number via MSG91 Widget API.
        Returns request ID (reqId) if successful, None otherwise.
        """
        # Parse and sanitize phone number format
        clean_phone = "".join(c for c in str(mobile_number) if c.isdigit())
        if clean_phone.startswith("91") and len(clean_phone) == 12:
            mobile_number = clean_phone
        elif len(clean_phone) > 10:
            mobile_number = clean_phone
        else:
            country_code = country_code.replace("+", "").strip() or "91"
            mobile_number = f"{country_code}{clean_phone}"
        
        if self.mock_mode:
            logger.info(f"📱 MOCK: Sent SMS OTP to {mobile_number}")
            return "msg91-mock-id"

        if not self.auth_key or not self.widget_id:
            logger.error("MSG91 credentials missing.")
            return None

        payload = {
            "widgetId": self.widget_id,
            "identifier": mobile_number,
        }
        
        headers = {
            "authkey": self.auth_key,
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/sendOtp",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()
                
                if data.get("type") == "success":
                    # MSG91 Widget API returns reqId in the `message` field
                    req_id = data.get("message")
                    return req_id
                else:
                    logger.error(f"Failed to send SMS OTP via MSG91: {data}")
                    return None
            except Exception as e:
                logger.error(f"Error sending SMS OTP: {str(e)}")
                return None

    async def verify_otp(self, verification_id: str, code: str, mobile_number: Optional[str] = None) -> bool:
        """
        Verify OTP code via MSG91 Widget API.
        """
        if self.mock_mode:
            logger.info(f"📱 MOCK: Verifying SMS OTP code {code}")
            return True

        if not self.auth_key or not self.widget_id:
            logger.error("MSG91 credentials missing.")
            return False
            
        payload = {
            "widgetId": self.widget_id,
            "reqId": verification_id,
            "otp": code,
        }
        
        headers = {
            "authkey": self.auth_key,
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/verifyOtp",
                    json=payload,
                    headers=headers
                )
                data = response.json()
                
                # Check for success in response
                if data.get("type") == "success":
                    access_token = data.get("message")
                    
                    if not access_token:
                        logger.error("MSG91 verifyOtp succeeded but no access token returned.")
                        return False
                        
                    # 2. Verify Access Token
                    token_payload = {
                        "access-token": access_token
                    }
                    
                    token_response = await client.post(
                        f"{self.base_url}/verifyAccessToken",
                        json=token_payload,
                        headers=headers
                    )
                    
                    token_data = token_response.json()
                    
                    if token_data.get("type") == "success":
                        logger.info("MSG91 Access Token verified successfully.")
                        return True
                    else:
                        logger.warning(f"MSG91 Access Token verification failed: {token_data}")
                        return False
                else:
                    logger.warning(f"SMS OTP verification failed via MSG91: {data}")
                    return False
            except Exception as e:
                logger.error(f"Error verifying SMS OTP: {str(e)}")
                return False

sms_service = SMSService()
