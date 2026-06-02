import asyncio
from app.services.gemini_service import GeminiService

async def main():
    service = GeminiService()
    # Test with a dummy image
    try:
        res = await service.parse_menu_file(b"dummydata123", "image/jpeg")
        print(res)
    except Exception as e:
        print("ERROR:", str(e))
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
