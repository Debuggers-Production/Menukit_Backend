import httpx

url = "https://pixabay.com/api/?key=56123521-df85c9fe398583c4be8b772f1&q=Lemon%20with%20grapes%20food&image_type=photo&category=food&min_width=400&min_height=400&safesearch=true&per_page=20&order=popular"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}

try:
    response = httpx.get(url, headers=headers)
    print("Pixabay API Status:", response.status_code)
    if response.status_code == 200:
        data = response.json()
        hits = data.get("hits", [])
        if hits:
            img_url = hits[0].get("largeImageURL")
            print("Trying to download:", img_url)
            img_res = httpx.get(img_url, headers=headers, follow_redirects=True)
            print("Download Status:", img_res.status_code)
            if img_res.status_code == 200:
                print("Download success, length:", len(img_res.content))
        else:
            print("No hits")
except Exception as e:
    print("Exception:", e)
