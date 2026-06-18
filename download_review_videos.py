import os
import requests
import time

OZON_CLIENT_ID = os.environ.get("OZON_CLIENT_ID")
OZON_API_KEY = os.environ.get("OZON_API_KEY")

if not OZON_CLIENT_ID or not OZON_API_KEY:
    print("Error: OZON_CLIENT_ID and OZON_API_KEY environment variables must be set.")
    exit(1)

HEADERS = {
    "Client-Id": OZON_CLIENT_ID,
    "Api-Key": OZON_API_KEY,
    "Content-Type": "application/json"
}

BASE_URL = "https://api-seller.ozon.ru"

def get_reviews():
    url = f"{BASE_URL}/v1/review/list"
    reviews = []
    last_id = ""
    has_next = True

    while has_next:
        payload = {
            "limit": 100,
            "status": "ALL",
            "sort_dir": "DESC"
        }
        if last_id:
            payload["last_id"] = last_id

        response = requests.post(url, headers=HEADERS, json=payload)
        if response.status_code != 200:
            print(f"Error {response.status_code}: {response.text}")
        response.raise_for_status()
        data = response.json()

        batch = data.get("reviews", [])
        reviews.extend(batch)

        has_next = data.get("has_next", False)
        last_id = data.get("last_id", "")
        print(f"Fetched {len(batch)} reviews. Total so far: {len(reviews)}.")
        time.sleep(1) # rate limiting
    return reviews

def get_review_info(review_id):
    url = f"{BASE_URL}/v1/review/info"
    payload = {"review_id": review_id}
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error fetching info for review {review_id}: {response.text}")
        return None

def download_video(url, filename):
    print(f"Downloading {url} to {filename}...")
    try:
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"Successfully downloaded {filename}")
    except Exception as e:
        print(f"Failed to download {url}: {e}")

def main():
    print("Fetching all reviews...")
    try:
        reviews = get_reviews()
    except Exception as e:
        print(f"Error fetching reviews: {e}")
        return

    print(f"Total reviews fetched: {len(reviews)}")

    videos_dir = "review_videos"
    if not os.path.exists(videos_dir):
        os.makedirs(videos_dir)

    for review in reviews:
        if review.get("videos_amount", 0) > 0:
            review_id = review["id"]
            print(f"Fetching detailed info for review {review_id} (has videos)...")
            info = get_review_info(review_id)
            if info and "videos" in info:
                for idx, video in enumerate(info["videos"]):
                    url = video.get("url")
                    if url:
                        ext = url.split('.')[-1]
                        # Handle URLs without extensions
                        if '?' in ext:
                            ext = ext.split('?')[0]
                        if len(ext) > 4 or not ext:
                            ext = "mp4" # Default to mp4

                        filename = os.path.join(videos_dir, f"review_{review_id}_video_{idx}.{ext}")
                        if not os.path.exists(filename):
                            download_video(url, filename)
                        else:
                            print(f"File {filename} already exists, skipping.")
            time.sleep(1) # rate limiting

    print("Done.")

if __name__ == "__main__":
    main()
