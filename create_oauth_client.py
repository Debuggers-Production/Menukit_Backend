import asyncio
import httpx

async def register_chatgpt_client():
    url = "http://localhost:8000/api/v1/oauth/register"
    data = {
        "client_name": "ChatGPT Menukit Client",
        "redirect_uris": "https://chatgpt.com/connector/oauth/zZ0wjyTcVJ3v",
        "scopes": "menukit.read menukit.write"
    }
    
    async with httpx.AsyncClient() as client:
        print(f"Registering client at {url}...")
        response = await client.post(url, data=data)
        
        if response.status_code == 200:
            client_data = response.json()
            print("\nSuccessfully Registered OAuth Client!")
            print("="*50)
            print(f"Client ID: {client_data['client_id']}")
            print("="*50)
        else:
            print(f"Failed to register client. Status: {response.status_code}")
            print(response.text)

if __name__ == "__main__":
    asyncio.run(register_chatgpt_client())
