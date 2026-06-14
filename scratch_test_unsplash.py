import httpx

url = "https://unsplash.com/napi/search/photos?query=pizza&per_page=5"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

response = httpx.get(url, headers=headers)
print(response.status_code)
if response.status_code == 200:
    data = response.json()
    for item in data.get("results", []):
        print(item.get("urls", {}).get("regular"))
