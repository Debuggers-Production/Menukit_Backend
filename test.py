# import sys
# import asyncio
# import httpx

# # Your MSG91 Credentials
# MSG91_AUTH_KEY = "548697AZzUomDG6a8609d3P1"
# MSG91_TEMPLATE_ID = "366873737968373233323535"

# SEND_URL = "https://control.msg91.com/api/v5/otp"
# VERIFY_URL = "https://control.msg91.com/api/v5/otp/verify"


# async def send_otp(mobile: str):
#     """Send OTP using standard MSG91 API."""
#     params = {
#         "template_id": MSG91_TEMPLATE_ID,
#         "mobile": mobile,
#         "authkey": MSG91_AUTH_KEY,
#     }

#     print(f"Sending OTP to {mobile}...")
#     async with httpx.AsyncClient(timeout=15) as client:
#         response = await client.post(
#             SEND_URL,
#             params=params,
#             headers={"Content-Type": "application/json"}
#         )

#     print("SEND STATUS:", response.status_code)
#     print("SEND RESPONSE:", response.text)
    
#     response.raise_for_status()
#     return response.json()


# async def verify_otp(mobile: str, otp: str):
#     """Verify OTP using standard MSG91 API."""
#     params = {
#         "mobile": mobile,
#         "otp": otp,
#     }

#     print(f"Verifying OTP {otp} for mobile {mobile}...")
#     async with httpx.AsyncClient(timeout=15) as client:
#         response = await client.get(
#             VERIFY_URL,
#             params=params,
#             headers={"authkey": MSG91_AUTH_KEY}
#         )

#     print("VERIFY STATUS:", response.status_code)
#     print("VERIFY RESPONSE:", response.text)
    
#     response.raise_for_status()
#     return response.json()


# async def main():
#     if len(sys.argv) < 2:
#         print("Usage:")
#         print("  To SEND an OTP:   python test.py <mobile_number>")
#         print("  To VERIFY an OTP: python test.py <mobile_number> <otp>")
#         print("Example: python test.py 918248692839")
#         sys.exit(1)

#     mobile = sys.argv[1]
    
#     if len(sys.argv) == 2:
#         # Just send OTP
#         try:
#             await send_otp(mobile)
#         except Exception as e:
#             print(f"Error sending OTP: {e}")
#     elif len(sys.argv) >= 3:
#         # Verify OTP
#         otp = sys.argv[2]
#         try:
#             await verify_otp(mobile, otp)
#         except Exception as e:
#             print(f"Error verifying OTP: {e}")

# if __name__ == "__main__":
#     asyncio.run(main())

import os
import asyncio
import httpx

async def main():
    key = "548697AZzUomDG6a8609d3P1"

    headers = {
        "authkey": key,
        "Content-Type": "application/json",
    }

    payload = {
        "widgetId": "366873737968373233323535",
        "identifier": "918248692839",
    }

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "https://api.msg91.com/api/v5/widget/sendOtp",
            headers=headers,
            json=payload,
        )

    print("STATUS:", r.status_code)
    print("BODY:", r.text)

asyncio.run(main())
