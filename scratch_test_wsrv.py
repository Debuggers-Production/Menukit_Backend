import httpx

url = "https://kidoneo.com/wp-content/uploads/2023/07/Pizza_1688814259.jpg"
proxy_url = f"https://wsrv.nl/?url={url}"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

try:
    response = httpx.get(proxy_url, headers=headers)
    print("Status:", response.status_code)
    print("Headers:", response.headers)
    print("Length:", len(response.content))
    if response.status_code == 200:
        print("Success!")
except Exception as e:
    print("Exception:", e)
