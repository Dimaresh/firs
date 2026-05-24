import requests
import json
import os

BASE_URL = 'https://api-seller.ozon.ru'

def get_headers(client_id, api_key):
    return {
        'Client-Id': client_id,
        'Api-Key': api_key,
        'Content-Type': 'application/json'
    }

def get_actions(client_id, api_key):
    """Fetches list of actions available for the seller."""
    url = f"{BASE_URL}/v1/actions"
    # The /v1/actions endpoint returns list of actions.
    response = requests.get(url, headers=get_headers(client_id, api_key))
    response.raise_for_status()
    # Assuming the API returns a list under 'result'
    return response.json().get('result', [])

def get_action_candidates(client_id, api_key, action_id, limit=100, offset=0):
    if not action_id:
        return []

    url = f"{BASE_URL}/v1/actions/candidates"
    try:
        aid = int(action_id)
    except (ValueError, TypeError):
        return []

    payload = {
        "action_id": aid,
        "limit": limit,
        "offset": offset
    }
    response = requests.post(url, headers=get_headers(client_id, api_key), json=payload)
    response.raise_for_status()
    return response.json().get('result', {}).get('products', [])

def add_products_to_action(client_id, api_key, action_id, products):
    if not action_id:
        return {}

    url = f"{BASE_URL}/v1/actions/products/activate"
    try:
        aid = int(action_id)
    except (ValueError, TypeError):
        return {}

    payload = {
        "action_id": aid,
        "products": products
    }
    response = requests.post(url, headers=get_headers(client_id, api_key), json=payload)
    response.raise_for_status()
    return response.json()

def remove_products_from_action(client_id, api_key, action_id, product_ids):
    if not action_id:
        return {}

    url = f"{BASE_URL}/v1/actions/products/deactivate"
    try:
        aid = int(action_id)
    except (ValueError, TypeError):
        return {}

    payload = {
        "action_id": aid,
        "product_ids": product_ids
    }
    response = requests.post(url, headers=get_headers(client_id, api_key), json=payload)
    response.raise_for_status()
    return response.json()

def rotate_products(client_id, api_key, action_id, count, state_file_path):
    """
    Core rotation logic:
    1. Read currently active products from state file.
    2. Remove them from action.
    3. Get new candidates (excluding removed).
    4. Add 'count' new products to action.
    5. Save new state.
    """
    if not client_id or not api_key or not action_id:
        raise ValueError("Client ID, API Key, and Action ID must be set.")

    state = {}
    if os.path.exists(state_file_path):
        with open(state_file_path, 'r') as f:
            state = json.load(f)

    # For simplicity, state could store action_id -> list of ids
    # Let's organize state by action_id
    action_key = str(action_id)
    current_active_ids = state.get(action_key, [])

    if current_active_ids:
        print(f"Removing {len(current_active_ids)} products from action {action_id}")
        remove_products_from_action(client_id, api_key, action_id, current_active_ids)

    candidates = get_action_candidates(client_id, api_key, action_id)
    available_candidates = [p for p in candidates if p['id'] not in current_active_ids]

    if len(available_candidates) < count:
        available_candidates = candidates # Fallback to all if not enough new ones

    new_products_to_add = []
    new_active_ids = []

    for candidate in available_candidates[:count]:
        new_products_to_add.append({
            "action_price": candidate.get('max_action_price', 0),
            "product_id": candidate['id']
        })
        new_active_ids.append(candidate['id'])

    if new_products_to_add:
        print(f"Adding {len(new_products_to_add)} products to action {action_id}")
        add_products_to_action(client_id, api_key, action_id, new_products_to_add)

        state[action_key] = new_active_ids
        with open(state_file_path, 'w') as f:
            json.dump(state, f)

        return {"status": "success", "added": new_active_ids, "removed": current_active_ids}
    else:
        return {"status": "success", "message": "No candidates available to add."}

def get_questions(client_id, api_key):
    """Fetches new, unanswered questions."""
    url = f"{BASE_URL}/v1/question/list"
    payload = {
        "filter": {
            "status": "NEW"
        },
        "limit": 100
    }
    response = requests.post(url, headers=get_headers(client_id, api_key), json=payload)
    response.raise_for_status()
    return response.json().get('result', [])

def answer_question(client_id, api_key, question_id, text):
    """Submits an answer to a question."""
    url = f"{BASE_URL}/v1/question/answer/create"
    try:
        qid = int(question_id)
    except (ValueError, TypeError):
        raise ValueError(f"Invalid question_id: {question_id}")
    payload = {
        "question_id": qid,
        "text": text
    }
    response = requests.post(url, headers=get_headers(client_id, api_key), json=payload)
    response.raise_for_status()
    return response.json()

def get_product_list(client_id, api_key, limit=1000):
    url = f"{BASE_URL}/v2/product/list"
    payload = {
        "filter": {"visibility": "ALL"},
        "limit": limit,
        "last_id": ""
    }
    response = requests.post(url, headers=get_headers(client_id, api_key), json=payload)
    response.raise_for_status()
    return response.json().get('result', {}).get('items', [])

def get_product_info_list(client_id, api_key, product_ids):
    if not product_ids:
        return []
    url = f"{BASE_URL}/v3/product/info/list"
    payload = {
        "product_id": product_ids
    }
    response = requests.post(url, headers=get_headers(client_id, api_key), json=payload)
    response.raise_for_status()
    return response.json().get('result', {}).get('items', [])

def get_product_stocks(client_id, api_key):
    url = f"{BASE_URL}/v3/product/info/stocks"
    payload = {
        "filter": {"visibility": "ALL"},
        "last_id": "",
        "limit": 1000
    }
    response = requests.post(url, headers=get_headers(client_id, api_key), json=payload)
    response.raise_for_status()
    return response.json().get('result', {}).get('items', [])

def get_product_prices(client_id, api_key):
    url = f"{BASE_URL}/v4/product/info/prices"
    payload = {
        "filter": {"visibility": "ALL"},
        "last_id": "",
        "limit": 1000
    }
    response = requests.post(url, headers=get_headers(client_id, api_key), json=payload)
    response.raise_for_status()
    return response.json().get('result', {}).get('items', [])

def update_product_prices(client_id, api_key, prices_data):
    """
    prices_data is a list of dicts: [{"product_id": 123, "price": "1500", "old_price": "2000", "auto_action_enabled": "UNKNOWN"}]
    """
    url = f"{BASE_URL}/v1/product/import/prices"
    payload = {
        "prices": prices_data
    }
    response = requests.post(url, headers=get_headers(client_id, api_key), json=payload)
    response.raise_for_status()
    return response.json()
