import httpx
import traceback

url = "https://kidoneo.com/wp-content/uploads/2023/07/Pizza_1688814259.jpg"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

try:
    response = httpx.get(url, headers=headers)
    print("Status:", response.status_code)
    print("Headers:", response.headers)
    print("Length:", len(response.content))
except Exception as e:
    print("Exception:")
    traceback.print_exc()
