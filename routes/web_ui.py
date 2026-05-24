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
    margin = float(data['margin'])

    margins = load_sku_margins()
    margins[sku] = margin
    save_sku_margins(margins)

    return jsonify({'success': True})
