import httpx
import asyncio

async def main():
    shop_id = "a79d6762-a231-4527-818e-af78af7caa4f"
    url = f"http://127.0.0.1:8000/api/v1/public/shop/{shop_id}"
    
    async with httpx.AsyncClient() as client:
        print(f"Requesting {url}")
        res = await client.get(url)
        print("GET shop:", res.status_code, res.text)
        
        url_menu = f"http://127.0.0.1:8000/api/v1/public/shop/{shop_id}/menu"
        res2 = await client.get(url_menu)
        print("GET menu:", res2.status_code, res2.text)

if __name__ == "__main__":
    asyncio.run(main())
