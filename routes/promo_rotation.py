import os
from flask import Blueprint, jsonify, request
import logging
from services.ozon_promo_rotator import run_promo_rotation, load_rotation_status

logger = logging.getLogger(__name__)

promo_rotation_bp = Blueprint('promo_rotation', __name__, url_prefix='/api/v1/promo')

def get_credentials():
    client_id = os.environ.get('OZON_CLIENT_ID')
    api_key = os.environ.get('OZON_API_KEY')
    return client_id, api_key

@promo_rotation_bp.route('/sync-now', methods=['POST'])
def force_sync():
    """Manually force-trigger the background rotation job."""
    client_id, api_key = get_credentials()

    if not client_id or not api_key:
        # Fallback to config file if env vars are missing
        import json
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                client_id = config.get("client_id")
                api_key = config.get("api_key")
        except Exception:
            pass

    if not client_id or not api_key:
        return jsonify({"error": "Missing Ozon credentials"}), 400

    data = request.get_json(silent=True) or {}
    action_id = data.get('action_id')

    if not action_id:
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                action_id = config.get("action_id")
        except Exception:
            pass

    if not action_id:
        return jsonify({"error": "Missing action_id"}), 400

    try:
        logger.info("Manual sync triggered.")
        result = run_promo_rotation(client_id, api_key, action_id)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.error(f"Error during manual sync: {e}")
        return jsonify({"error": str(e)}), 500

@promo_rotation_bp.route('/status', methods=['GET'])
def get_status():
    """Returns structured JSON response with execution status."""
    try:
        status = load_rotation_status()
        return jsonify(status)
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        return jsonify({"error": str(e)}), 500
