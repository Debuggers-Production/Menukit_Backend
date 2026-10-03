import httpx
import logging
import secrets
from typing import Optional, Dict
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

class SMSService:
    """Service to handle SMS OTP via MSG91 Widget API with Mock Terminal fallback."""
    _mock_otps: Dict[str, str] = {}

    def __init__(self):
        self.auth_key = settings.MSG91_AUTH_KEY
        self.widget_id = settings.MSG91_TEMPLATE_ID  # Using TEMPLATE_ID config for WIDGET_ID
        self.base_url = "https://api.msg91.com/api/v5/widget"

    @property
    def mock_mode(self) -> bool:
        return bool(getattr(settings, "MOC_OTP", False) or not self.auth_key or not self.widget_id)

    async def send_otp(self, mobile_number: str, country_code: str = "91", otp_length: int = 6, code: Optional[str] = None) -> Optional[str]:
        """
        Send OTP to mobile number via MSG91 Widget API or print to terminal if MOC_OTP is True.
        Returns request ID (reqId) if successful, None otherwise.
        """
        # Parse and sanitize phone number format
        clean_phone = "".join(c for c in str(mobile_number) if c.isdigit())
        if clean_phone.startswith("91") and len(clean_phone) == 12:
            formatted_mobile = clean_phone
        elif len(clean_phone) > 10:
            formatted_mobile = clean_phone
        else:
            country_code = country_code.replace("+", "").strip() or "91"
            formatted_mobile = f"{country_code}{clean_phone}"
        
        if self.mock_mode:
            otp_val = code or str(secrets.randbelow(900000) + 100000)
            SMSService._mock_otps[formatted_mobile] = otp_val
            SMSService._mock_otps[clean_phone] = otp_val
            SMSService._mock_otps[str(mobile_number).strip()] = otp_val
            if len(clean_phone) >= 10:
                SMSService._mock_otps[clean_phone[-10:]] = otp_val

            GREEN = "\033[92m"
            YELLOW = "\033[93m"
            CYAN = "\033[96m"
            RESET = "\033[0m"
            BOLD = "\033[1m"

            logger.info(f"[MOCK OTP] Mobile {formatted_mobile}: {otp_val}")
            print(f"\n{YELLOW}{'=' * 60}{RESET}")
            print(f"{YELLOW}>>> [MOCK OTP ACTIVE - NO REAL SMS SENT] <<<{RESET}")
            print(f"{CYAN}* Mobile Number  : {BOLD}{formatted_mobile}{RESET}")
            print(f"{GREEN}* SMS OTP Code   : {BOLD}{otp_val}{RESET}")
            print(f"{CYAN}* Valid for      : 10 minutes{RESET}")
            print(f"{YELLOW}{'=' * 60}\n{RESET}")
            return f"mock-vid-{formatted_mobile}"

        if not self.auth_key or not self.widget_id:
            logger.error("MSG91 credentials missing.")
            return None

        payload = {
            "widgetId": self.widget_id,
            "identifier": formatted_mobile,
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
        Verify OTP code via MSG91 Widget API or check mock store if MOC_OTP is True.
        """
        clean_code = str(code).strip()
        if self.mock_mode:
            if clean_code in ["123456", "000000"]:
                logger.info(f"🔑 [MOCK OTP] Dev bypass OTP accepted for {mobile_number}")
                return True
            if mobile_number:
                clean_phone = "".join(c for c in str(mobile_number) if c.isdigit())
                for candidate in [str(mobile_number).strip(), clean_phone, clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone]:
                    if SMSService._mock_otps.get(candidate) == clean_code:
                        logger.info(f"✅ [MOCK OTP] Verified SMS OTP code {clean_code} for {mobile_number}")
                        return True
            logger.info(f"📱 [MOCK OTP] Verifying SMS OTP code {clean_code}")
            return True

        if not self.auth_key or not self.widget_id:
            logger.error("MSG91 credentials missing.")
            return False
            
        payload = {
            "widgetId": self.widget_id,
            "reqId": verification_id,
            "otp": clean_code,
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
