import asyncio
from google import genai
from app.core.config import get_settings

settings = get_settings()

async def test_model(model_name):
    print(f"Testing {model_name}...")
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=model_name,
            contents="Hello"
        )
        print(f"✅ SUCCESS with {model_name}")
        return True
    except Exception as e:
        print(f"❌ FAILED with {model_name}: {str(e)[:200]}")
        return False

async def main():
    print(f"Using API Key: {settings.GEMINI_API_KEY[:10]}...")
    models = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-2.5-pro']
    for m in models:
        await test_model(m)

if __name__ == "__main__":
    asyncio.run(main())
