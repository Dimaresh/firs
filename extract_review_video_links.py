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
LINKS_FILE = "video_links.txt"

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

def main():
    print("Fetching all reviews...")
    try:
        reviews = get_reviews()
    except Exception as e:
        print(f"Error fetching reviews: {e}")
        return

    print(f"Total reviews fetched: {len(reviews)}")

    links = []

    for review in reviews:
        if review.get("videos_amount", 0) > 0:
            review_id = review["id"]
            print(f"Fetching detailed info for review {review_id} (has videos)...")
            info = get_review_info(review_id)
            if info and "videos" in info:
                for video in info["videos"]:
                    url = video.get("url")
                    if url:
                        links.append(url)
                        print(f"Found video link: {url}")
            time.sleep(1) # rate limiting

    print(f"Found {len(links)} video links in total.")
    if links:
        with open(LINKS_FILE, "w") as f:
            for link in links:
                f.write(f"{link}\n")
        print(f"Links have been saved to {LINKS_FILE}")
    else:
        print("No video links were found.")

if __name__ == "__main__":
    main()
