import httpx
import base64
import logging
from typing import Optional, Dict, Any
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

class SMSService:
    """Service to handle SMS OTP via Message Central VerifyNow API."""

    def __init__(self):
        self.base_url = "https://cpaas.messagecentral.com"
        self.customer_id = settings.MESSAGE_CENTRAL_CUSTOMER_ID
        self.password = settings.MESSAGE_CENTRAL_PASSWORD
        self.mock_mode = settings.MOC_OTP

    async def _get_auth_token(self) -> Optional[str]:
        """Fetch auth token from Message Central."""
        if not self.customer_id or not self.password:
            logger.error("Message Central credentials missing.")
            return None

        # Base64 encode the password as per docs
        b64_password = base64.b64encode(self.password.encode('utf-8')).decode('utf-8')
        
        url = f"{self.base_url}/auth/v1/authentication/token"
        params = {
            "customerId": self.customer_id,
            "key": b64_password,
            "scope": "NEW",
            "country": "91"
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
                if (data.get("status") in (200, "200") or data.get("responseCode") in (200, "200")) and data.get("token"):
                    return data.get("token")
                else:
                    logger.error(f"Failed to get Message Central token: {data}")
                    return None
            except Exception as e:
                logger.error(f"Error fetching auth token: {str(e)}")
                return None

    async def send_otp(self, mobile_number: str, country_code: str = "91", otp_length: int = 6) -> Optional[str]:
        """
        Send OTP to mobile number.
        Returns verificationId if successful, None otherwise.
        """
        # Parse and sanitize phone number format (matching Dauth service)
        clean_phone = "".join(c for c in str(mobile_number) if c.isdigit())
        if clean_phone.startswith("91") and len(clean_phone) == 12:
            country_code = "91"
            mobile_number = clean_phone[2:]
        elif len(clean_phone) > 10:
            country_code = clean_phone[:-10]
            mobile_number = clean_phone[-10:]
        else:
            mobile_number = clean_phone
            country_code = country_code.replace("+", "").strip() or "91"
        
        if self.mock_mode:
            logger.info(f"📱 MOCK: Sent SMS OTP to {mobile_number}")
            print(f"📱 MOCK: Sent SMS OTP to {mobile_number} | Mock verificationId: mock-verify-id")
            return "mock-verify-id"

        token = await self._get_auth_token()
        if not token:
            return None

        url = f"{self.base_url}/verification/v3/send"
        params = {
            "customerId": self.customer_id,
            "countryCode": country_code,
            "flowType": "SMS",
            "mobileNumber": mobile_number,
            "otpLength": otp_length
        }
        headers = {
            "authToken": token
        }

        async with httpx.AsyncClient() as client:
            try:
                # Based on docs & Dauth service, send POST request with query parameters including customerId
                response = await client.post(url, params=params, headers=headers)
                response.raise_for_status()
                data = response.json()
                if (data.get("responseCode") in (200, "200") or data.get("status") in (200, "200")) and data.get("data"):
                    # The API docs show 'verficationId' (typo) in the JSON response, handle both
                    return data["data"].get("verificationId") or data["data"].get("verficationId")
                else:
                    logger.error(f"Failed to send SMS OTP: {data}")
                    return None
            except Exception as e:
                logger.error(f"Error sending SMS OTP: {str(e)}")
                return None

    async def verify_otp(self, verification_id: str, code: str) -> bool:
        """
        Verify OTP code.
        """
        if self.mock_mode:
            logger.info(f"📱 MOCK: Verifying SMS OTP code {code} for verificationId {verification_id}")
            # In mock mode, assume any 4 digit code is valid, or just return True
            return True

        if not verification_id:
            return False

        token = await self._get_auth_token()
        if not token:
            return False

        url = f"{self.base_url}/verification/v3/validateOtp"
        params = {
            "verificationId": verification_id,
            "code": code
        }
        headers = {
            "authToken": token
        }

        async with httpx.AsyncClient() as client:
            try:
                # The doc says POST for validateOtp path but cURL has no POST method. We'll use GET as query parameters are passed in cURL. If it fails, we should change to POST.
                response = await client.get(url, params=params, headers=headers)
                data = response.json()
                
                # Check if it fails with 405 Method Not Allowed, fallback to POST
                if response.status_code == 405:
                     response = await client.post(url, params=params, headers=headers)
                     data = response.json()
                
                if (data.get("responseCode") in (200, "200") or data.get("status") in (200, "200")) and data.get("data", {}).get("verificationStatus") == "VERIFICATION_COMPLETED":
                    return True
                else:
                    logger.warning(f"SMS OTP verification failed: {data}")
                    return False
            except Exception as e:
                logger.error(f"Error verifying SMS OTP: {str(e)}")
                return False

sms_service = SMSService()
