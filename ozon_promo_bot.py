import requests
import json
import os
import time

# Ozon API credentials (to be set as environment variables or config)
CLIENT_ID = os.environ.get('OZON_CLIENT_ID', 'your_client_id')
API_KEY = os.environ.get('OZON_API_KEY', 'your_api_key')
ACTION_ID = os.environ.get('OZON_ACTION_ID', 'your_action_id')

HEADERS = {
    'Client-Id': CLIENT_ID,
    'Api-Key': API_KEY,
    'Content-Type': 'application/json'
}

BASE_URL = 'https://api-seller.ozon.ru'
# Use absolute path for state file based on current script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, 'promo_state.json')

def get_action_candidates(action_id):
    """Fetches products that can be added to the action."""
    url = f"{BASE_URL}/v1/actions/candidates"
    payload = {
        "action_id": int(action_id),
        "limit": 100,
        "offset": 0
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    return response.json().get('result', {}).get('products', [])

def add_products_to_action(action_id, products):
    """Adds a list of products to an action."""
    url = f"{BASE_URL}/v1/actions/products/activate"
    payload = {
        "action_id": int(action_id),
        "products": products
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    print(f"Successfully added products to action {action_id}")
    return response.json()

def remove_products_from_action(action_id, product_ids):
    """Removes a list of products from an action."""
    url = f"{BASE_URL}/v1/actions/products/deactivate"
    payload = {
        "action_id": int(action_id),
        "product_ids": product_ids
    }
    response = requests.post(url, headers=HEADERS, json=payload)
    response.raise_for_status()
    print(f"Successfully removed products from action {action_id}")
    return response.json()

def rotate_promo_products():
    """Main logic to rotate 5 products in the promotion."""
    print("Starting product rotation...")

    if CLIENT_ID == 'your_client_id' or API_KEY == 'your_api_key' or ACTION_ID == 'your_action_id':
        print("API credentials are not set. Exiting.")
        return

    try:
        state = {}
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)

        current_active_ids = state.get('active_product_ids', [])

        if current_active_ids:
            # Remove currently active products
            print(f"Removing products: {current_active_ids}")
            remove_products_from_action(ACTION_ID, current_active_ids)

        # Get candidates
        candidates = get_action_candidates(ACTION_ID)

        # Filter out products that were just active (simple rotation)
        available_candidates = [p for p in candidates if p['id'] not in current_active_ids]

        if len(available_candidates) < 5:
            # If we don't have enough new ones, just take any 5
            available_candidates = candidates

        # Select 5 new products
        new_products_to_add = []
        new_active_ids = []

        for candidate in available_candidates[:5]:
            new_products_to_add.append({
                "action_price": candidate.get('max_action_price', 0),
                "product_id": candidate['id']
            })
            new_active_ids.append(candidate['id'])

        if new_products_to_add:
            print(f"Adding new products: {new_active_ids}")
            add_products_to_action(ACTION_ID, new_products_to_add)

            # Update state
            with open(STATE_FILE, 'w') as f:
                json.dump({'active_product_ids': new_active_ids}, f)
        else:
            print("No candidates available to add.")

    except Exception as e:
        print(f"An error occurred during rotation: {e}")

if __name__ == "__main__":
    rotate_promo_products()
