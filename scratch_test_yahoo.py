import httpx
import re

url = "https://images.search.yahoo.com/search/images;?p=pizza+food"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

response = httpx.get(url, headers=headers)
print(response.status_code)
if response.status_code == 200:
    html = response.text
    # Yahoo stores image data in a JS variable:
    # imgurl":"https://...","
    matches = re.findall(r'"imgurl":"([^"]+)"', html)
    print("Found:", len(matches))
    for m in matches[:5]:
        # They might be escaped
        print(m.replace('\\/', '/'))
