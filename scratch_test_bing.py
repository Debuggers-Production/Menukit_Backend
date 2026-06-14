import httpx
import re

url = "https://www.bing.com/images/search?q=pizza+food"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

response = httpx.get(url, headers=headers)
print(response.status_code)
if response.status_code == 200:
    html = response.text
    # Bing stores image data in m="..." where m is JSON encoded
    matches = re.findall(r'murl&quot;:&quot;(.*?)&quot;', html)
    print("Found:", len(matches))
    for m in matches[:5]:
        print(m)
