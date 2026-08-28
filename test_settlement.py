import asyncio
import razorpay
from app.core.config import get_settings

async def test_fetch():
    settings = get_settings()
    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    
    try:
        print("Fetching transfer...")
        transfer = client.transfer.fetch('trf_TPY0hHAIIuTZHX')
        print(transfer)
        
        settlement_id = transfer.get("recipient_settlement_id")
        if settlement_id:
            print(f"Fetching settlement {settlement_id}...")
            settlement = client.settlement.fetch(settlement_id)
            print(settlement)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_fetch())
