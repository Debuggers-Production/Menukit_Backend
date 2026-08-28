import asyncio
import razorpay
from app.core.config import get_settings
import requests
from requests.auth import HTTPBasicAuth

async def test_fetch():
    settings = get_settings()
    
    try:
        print("Fetching settlement setl_TR9i9UhWChPRu0 from linked account...")
        
        # We can just make a direct HTTP request to avoid SDK limitations
        url = "https://api.razorpay.com/v1/settlements/setl_TR9i9UhWChPRu0"
        headers = {
            "X-Razorpay-Account": "acc_TPN7vozxtijuDV"
        }
        
        response = requests.get(
            url, 
            headers=headers, 
            auth=HTTPBasicAuth(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
        print(response.json())
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_fetch())
