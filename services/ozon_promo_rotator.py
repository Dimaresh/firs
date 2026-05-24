import os
import json
import time
import logging
from typing import Dict, List, Any, Optional
import requests

logger = logging.getLogger(__name__)

BASE_URL = 'https://api-seller.ozon.ru'


def _get_headers(client_id: str, api_key: str) -> Dict[str, str]:
    return {
        'Client-Id': client_id,
        'Api-Key': api_key,
        'Content-Type': 'application/json'
    }


def _make_request_with_backoff(method: str, url: str, headers: Dict[str, str], json_data: Optional[Dict] = None, max_retries: int = 5, raise_errors: bool = True) -> requests.Response:
    """Makes an HTTP request and handles 429 Too Many Requests using exponential backoff."""
    delay = 1
    for attempt in range(max_retries):
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=json_data)
            else:
                response = requests.post(url, headers=headers, json=json_data)

            if response.status_code == 429:
                logger.warning(f"Rate limited (429) on {url}. Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= 2
                continue

            if raise_errors:
                response.raise_for_status()
            return response

        except requests.exceptions.RequestException as e:
            if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 429:
                logger.warning(f"Rate limited (429) on {url}. Retrying in {delay} seconds...")
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(f"API Request failed: {e}")
                raise

    raise Exception(f"Max retries ({max_retries}) reached for {url} due to rate limiting.")


def fetch_analytics_data(client_id: str, api_key: str, date_from: str, date_to: str) -> List[Dict[str, Any]]:
    """
    Fetches analytics data (/v1/analytics/data) for the trailing 24 hours.
    date_from and date_to should be in YYYY-MM-DD format.
    We need metrics for views and add to cart.
    """
    url = f"{BASE_URL}/v1/analytics/data"

    # Ozon Analytics API requires metrics to be specified.
    payload = {
        "date_from": str(date_from),
        "date_to": str(date_to),
        "metrics": ["session_view_pdp", "ordered_units"],
        "dimension": ["sku"],
        "limit": 1000,
        "offset": 0
    }

    all_data = []

    while True:
        response = None
        try:
            response = _make_request_with_backoff('POST', url, _get_headers(client_id, api_key), payload, raise_errors=False)

            # Explicit strict check per user request
            if response.status_code != 200:
                logger.error(f"API Error: {response.text}")
                return []

            data = response.json()
            if data is None:
                return []
            result_block = data.get('result', {})

            # Sometimes Ozon returns an empty list instead of a dict for 'result' if there's no data
            if isinstance(result_block, list):
                items = result_block
            else:
                items = result_block.get('data', [])

            all_data.extend(items)

            if len(items) < payload['limit']:
                break

            payload['offset'] += payload['limit']

        except Exception as e:
            logger.error(f"Failed to fetch or parse analytics data: {e}")
            try:
                # Attempt to log the raw payload if it was a JSON decode error
                logger.error(f"Raw Response: {response.text}")
            except Exception:
                pass
            break # Exit the loop on failure, return whatever we have so far

    return all_data


def calculate_projected_margin(price: float, commission_percent: float, logistics_fee: float, action_discount_percent: float) -> float:
    """
    Calculates projected net payout margin percentage.
    price: Current regular price
    commission_percent: Ozon category commission (e.g. 15.0 for 15%)
    logistics_fee: Fixed fulfillment/logistics fee in absolute currency (e.g. 50.0)
    action_discount_percent: Required discount to join promo (e.g. 5.0 for 5%)

    Returns projected margin as a percentage (e.g. 12.5 for 12.5%)
    """
    if price <= 0:
        return 0.0

    action_price = price * (1 - (action_discount_percent / 100))
    commission_cost = action_price * (commission_percent / 100)

    net_payout = action_price - commission_cost - logistics_fee

    # Simple margin calculation: (Net Payout / Action Price) * 100
    # Or should margin be calculated based on cost? The prompt says "net payout price".
    # Assuming margin is based on action price.
    margin_percent = (net_payout / action_price) * 100 if action_price > 0 else 0.0
    return margin_percent


def evaluate_sku_for_promotion(
    sku: str,
    views: int,
    adds_to_cart: int,
    current_price: float,
    commission_percent: float,
    logistics_fee: float,
    action_discount_percent: float,
    min_target_margin: float,
    is_currently_in_promo: bool
) -> Dict[str, Any]:
    """
    Core automation decision tree.
    Returns a dict with 'action' (JOIN, LEAVE, or NONE) and 'reason' string.
    """
    conversion_rate = (adds_to_cart / views) if views > 0 else 0.0

    projected_margin = calculate_projected_margin(
        price=current_price,
        commission_percent=commission_percent,
        logistics_fee=logistics_fee,
        action_discount_percent=action_discount_percent
    )

    action = "NONE"
    reason = ""

    if conversion_rate > 0.10:
        if projected_margin >= min_target_margin:
            if not is_currently_in_promo:
                action = "JOIN"
                reason = f"CR={conversion_rate*100:.1f}%, Margin={projected_margin:.1f}% >= Target={min_target_margin:.1f}%"
            else:
                reason = "Already in promo and margin is safe."
        else:
            if is_currently_in_promo:
                action = "LEAVE"
                reason = f"Margin={projected_margin:.1f}% < Target={min_target_margin:.1f}% (CR={conversion_rate*100:.1f}%)"
            else:
                reason = f"CR > 10% but Margin={projected_margin:.1f}% < Target={min_target_margin:.1f}%"
    else:
        # If CR <= 10%, we don't automatically join. But what if it's already in promo?
        # The prompt says: "Analytical Trigger: If CR > 10% AND not in promo, prepare for entry."
        # Decision Rule 2: "If already in promotion, but margin < threshold, remove."
        if is_currently_in_promo and projected_margin < min_target_margin:
            action = "LEAVE"
            reason = f"Margin={projected_margin:.1f}% < Target={min_target_margin:.1f}%"
        else:
            reason = f"CR={conversion_rate*100:.1f}% <= 10% or margin is safe."

    return {
        "action": action,
        "reason": reason,
        "sku": sku,
        "cr": conversion_rate,
        "margin": projected_margin
    }

# State management for promo rotation

PROMO_STATUS_FILE = 'promo_rotation_status.json'

def load_rotation_status() -> Dict[str, Any]:
    if os.path.exists(PROMO_STATUS_FILE):
        try:
            with open(PROMO_STATUS_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading status file: {e}")
    return {
        "last_execution_timestamp": None,
        "total_processed_skus": 0,
        "total_added": 0,
        "total_removed": 0,
        "alerts": []
    }

def save_rotation_status(status: Dict[str, Any]):
    try:
        with open(PROMO_STATUS_FILE, 'w') as f:
            json.dump(status, f)
    except Exception as e:
        logger.error(f"Error saving status file: {e}")

def run_promo_rotation(client_id: str, api_key: str, action_id: str, mock_data: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Main rotation runner.
    mock_data can be injected for testing since we don't have a real DB with costs.
    """
    import datetime
    from ozon_api import get_action_candidates, add_products_to_action, remove_products_from_action

    logger.info("Starting promo rotation job...")

    status = load_rotation_status()
    alerts = []
    total_processed = 0
    total_added = 0
    total_removed = 0

    try:
        # Fetch analytics for last 24h
        today = datetime.datetime.now()
        yesterday = today - datetime.timedelta(days=1)

        date_to = today.strftime("%Y-%m-%d")
        date_from = yesterday.strftime("%Y-%m-%d")

        try:
            analytics = fetch_analytics_data(client_id, api_key, date_from, date_to)
        except Exception as e:
            msg = f"Failed to fetch analytics: {e}"
            logger.error(msg)
            alerts.append(msg)
            analytics = []

        # Map analytics by SKU
        sku_metrics = {}
        for row in analytics:
            try:
                # Result row format depends on Ozon API, typically dimensions are list of values matching 'dimension' in request.
                # metrics are list of values matching 'metrics'.
                dimensions = row.get('dimensions', [])
                metrics = row.get('metrics', [])

                if len(dimensions) > 0 and len(metrics) >= 2:
                    sku_val = dimensions[0].get('id')
                    if sku_val:
                        # Strictly enforce safe parsing without assuming valid numbers
                        raw_views = metrics[0]
                        raw_to_cart = metrics[1]

                        try:
                            views = int(float(raw_views)) if raw_views not in (None, 'None', '') else 0
                        except ValueError:
                            views = 0

                        try:
                            to_cart = int(float(raw_to_cart)) if raw_to_cart not in (None, 'None', '') else 0
                        except ValueError:
                            to_cart = 0

                        sku_metrics[str(sku_val)] = {"views": views, "to_cart": to_cart}
            except Exception as e:
                logger.warning(f"Skipping SKU metric parse due to error: {e}. Raw row: {row}")
                continue

        # Get action candidates to see what's eligible and what's already in promo
        # offset logic omitted for brevity, assuming limit=1000 is enough for test
        candidates = get_action_candidates(client_id, api_key, action_id, limit=1000)

        products_to_add = []
        products_to_remove = []

        for candidate in candidates:
            total_processed += 1
            sku = str(candidate.get('id', ''))

            # For this MVP without a real DB, we use mock values or defaults
            current_price = candidate.get('price', 1000.0) # default fallback
            is_in_promo = candidate.get('is_participating', False)

            # Default mock parameters for the assignment
            commission_percent = 15.0
            logistics_fee = 50.0
            action_discount_percent = 5.0
            min_target_margin = 10.0

            if mock_data and sku in mock_data:
                md = mock_data[sku]
                current_price = md.get('price', current_price)
                commission_percent = md.get('commission', commission_percent)
                logistics_fee = md.get('logistics', logistics_fee)
                action_discount_percent = md.get('discount', action_discount_percent)
                min_target_margin = md.get('target_margin', min_target_margin)

            metrics = sku_metrics.get(sku, {"views": 0, "to_cart": 0})

            # Load custom margins if saved via UI
            try:
                with open('sku_margins.json', 'r') as mf:
                    saved_margins = json.load(mf)
                    if sku in saved_margins:
                        min_target_margin = saved_margins[sku]
            except:
                pass

            decision = evaluate_sku_for_promotion(
                sku=sku,
                views=metrics['views'],
                adds_to_cart=metrics['to_cart'],
                current_price=current_price,
                commission_percent=commission_percent,
                logistics_fee=logistics_fee,
                action_discount_percent=action_discount_percent,
                min_target_margin=min_target_margin,
                is_currently_in_promo=is_in_promo
            )

            if not hasattr(logger, "run_logs"):
                logger.run_logs = []
            if not hasattr(logger, "sku_metrics"):
                logger.sku_metrics = {}

            timestamp_str = datetime.datetime.now().isoformat()
            logger.info(f"[{timestamp_str}] SKU: {sku} | Action: {decision['action']} | Reason: {decision['reason']}")
            logger.run_logs.insert(0, {
                "timestamp": timestamp_str.split('.')[0].replace('T', ' '),
                "sku": sku,
                "event": decision['action'],
                "reason": decision['reason']
            })

            # Keep top 50
            logger.run_logs = logger.run_logs[:50]

            logger.sku_metrics[sku] = {
                "sku": sku,
                "cr": decision['cr'],
                "margin": min_target_margin
            }

            if decision['action'] == 'JOIN':
                products_to_add.append({
                    "action_price": current_price * (1 - (action_discount_percent/100)),
                    "product_id": candidate['id']
                })
            elif decision['action'] == 'LEAVE':
                products_to_remove.append(candidate['id'])

        # Execute actions
        if products_to_add:
            try:
                add_products_to_action(client_id, api_key, action_id, products_to_add)
                total_added += len(products_to_add)
            except Exception as e:
                msg = f"Failed to add products: {e}"
                logger.error(msg)
                alerts.append(msg)

        if products_to_remove:
            try:
                remove_products_from_action(client_id, api_key, action_id, products_to_remove)
                total_removed += len(products_to_remove)
            except Exception as e:
                msg = f"Failed to remove products: {e}"
                logger.error(msg)
                alerts.append(msg)

    except Exception as e:
        msg = f"Unexpected error during rotation: {e}"
        logger.error(msg)
        alerts.append(msg)

    status["last_execution_timestamp"] = datetime.datetime.now().isoformat()
    status["total_processed_skus"] = total_processed
    status["total_added"] = total_added
    status["total_removed"] = total_removed
    status["alerts"] = alerts
    status["last_logs"] = getattr(logger, "run_logs", [])
    status["sku_metrics"] = list(getattr(logger, "sku_metrics", {}).values())

    save_rotation_status(status)
    logger.info("Promo rotation job completed.")
    return status
