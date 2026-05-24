import json
import os
import logging
from flask import Blueprint, render_template, request, jsonify

from services.ozon_promo_rotator import load_rotation_status

logger = logging.getLogger(__name__)

web_ui_bp = Blueprint('web_ui', __name__)

SKU_CONFIG_FILE = 'sku_margins.json'

def load_sku_margins():
    if os.path.exists(SKU_CONFIG_FILE):
        try:
            with open(SKU_CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading SKU margins: {e}")
    return {}

def save_sku_margins(margins):
    try:
        with open(SKU_CONFIG_FILE, 'w') as f:
            json.dump(margins, f)
    except Exception as e:
        logger.error(f"Error saving SKU margins: {e}")

@web_ui_bp.route('/')
def dashboard():
    status = load_rotation_status()
    # In a real app we'd load logs from a DB, here we might pull from status alerts or recent runs
    # For MVP, we can synthesize a 'logs' list from the status object if we adapt rotator to save them
    logs = status.get('last_logs', [])

    action_id = None
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            action_id = config.get("action_id")
    except Exception:
        pass

    # We must format alerts/logs to match the template expectations
    return render_template('dashboard.html', status=status, logs=logs, action_id=action_id)

@web_ui_bp.route('/settings')
def settings():
    # Load status to get list of SKUs and recent CRs
    status = load_rotation_status()
    margins = load_sku_margins()

    skus_data = status.get('sku_metrics', [])

    # Merge saved margins into the view data
    for item in skus_data:
        sku = item.get('sku')
        if sku in margins:
            item['margin'] = margins[sku]
        else:
            item['margin'] = item.get('margin', 10.0) # default

    return render_template('settings.html', skus=skus_data)

@web_ui_bp.route('/settings/update', methods=['POST'])
def update_margin():
    data = request.get_json()
    if not data or 'sku' not in data or 'margin' not in data:
        return jsonify({'error': 'Invalid payload'}), 400

    sku = str(data['sku'])
    try:
        margin = float(data['margin'])
    except (ValueError, TypeError):
        return jsonify({'error': 'Margin must be a valid number'}), 400

    margins = load_sku_margins()
    margins[sku] = margin
    save_sku_margins(margins)

    return jsonify({'success': True})

import ozon_api

@web_ui_bp.route('/margin')
def margin_checker():
    # Load credentials
    client_id = None
    api_key = None
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            client_id = config.get("client_id")
            api_key = config.get("api_key")
    except Exception:
        pass

    client_id = os.environ.get('OZON_CLIENT_ID', client_id)
    api_key = os.environ.get('OZON_API_KEY', api_key)

    if not client_id or not api_key:
        return render_template('margin.html', error="Ozon credentials missing. Please configure them in settings.")

    try:
        # Get products
        product_list = ozon_api.get_product_list(client_id, api_key)
        product_ids = [p['product_id'] for p in product_list]

        # We need to chunk product_ids if there are too many, but for now we'll assume < 1000
        # Wait, the limit is usually 1000 for stocks and prices too

        # Get stocks
        stocks = ozon_api.get_product_stocks(client_id, api_key)
        stock_map = {}
        for s in stocks:
            # sum all stocks
            total_stock = sum([st['present'] for st in s.get('stocks', [])])
            stock_map[str(s['product_id'])] = total_stock

        # Filter products with stock > 0
        in_stock_ids = [str(pid) for pid in product_ids if stock_map.get(str(pid), 0) > 0]

        # Get prices
        prices = ozon_api.get_product_prices(client_id, api_key)

        products_data = []
        for p in prices:
            pid = str(p['product_id'])
            if pid in in_stock_ids:
                sku = str(p.get('offer_id', ''))
                name = str(p.get('name', sku))  # Fallback to sku if name is not in prices (it usually isn't, but let's check)

                # Prices are inside 'price' dict
                price_info = p.get('price', {})
                current_price = float(price_info.get('price', 0))

                # We need to compute margin:
                # To do this correctly, we need commissions. The prompt suggests a 15% commission + 50 logistics.
                # Let's use the same mockup parameters from rotator: commission 15%, logistics 50.
                if current_price > 0:
                    margin_abs = current_price - (current_price * 0.15) - 50.0
                    margin_pct = (margin_abs / current_price) * 100
                else:
                    margin_pct = 0.0

                products_data.append({
                    "product_id": pid,
                    "sku": sku,
                    "stock": stock_map.get(pid, 0),
                    "price": current_price,
                    "margin": round(margin_pct, 1)
                })

        return render_template('margin.html', products=products_data)

    except Exception as e:
        logger.error(f"Error fetching margin data: {e}", exc_info=True)
        return render_template('margin.html', error=str(e))

@web_ui_bp.route('/margin/update_price', methods=['POST'])
def update_product_price():
    data = request.get_json()
    product_id = data.get('product_id')
    new_price = data.get('new_price')

    if not product_id or not new_price:
        return jsonify({'error': 'Invalid payload'}), 400

    client_id = None
    api_key = None
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
            client_id = config.get("client_id")
            api_key = config.get("api_key")
    except Exception:
        pass

    client_id = os.environ.get('OZON_CLIENT_ID', client_id)
    api_key = os.environ.get('OZON_API_KEY', api_key)

    if not client_id or not api_key:
        return jsonify({'error': 'Missing credentials'}), 400

    try:
        # According to ozon api, old_price is optional but recommended. We'll just pass auto_action_enabled: UNKNOWN
        prices_data = [{
            "product_id": int(product_id),
            "price": str(new_price),
            "auto_action_enabled": "UNKNOWN"
        }]
        result = ozon_api.update_product_prices(client_id, api_key, prices_data)
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        logger.error(f"Error updating price: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
