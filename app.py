from flask import Flask, render_template, request, jsonify, redirect, url_for
import json
import os
import atexit
from apscheduler.schedulers.background import BackgroundScheduler
import ozon_api
import llm_helper
import logging

from routes.promo_rotation import promo_rotation_bp
from routes.web_ui import web_ui_bp
from services.ozon_promo_rotator import run_promo_rotation

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.register_blueprint(promo_rotation_bp)
app.register_blueprint(web_ui_bp)

CONFIG_FILE = 'config.json'
STATE_FILE = 'promo_state.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"client_id": "", "api_key": "", "action_id": "", "count": 5, "openai_api_key": ""}

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}

def background_rotation():
    config = load_config()
    client_id = os.environ.get('OZON_CLIENT_ID') or config.get("client_id")
    api_key = os.environ.get('OZON_API_KEY') or config.get("api_key")
    action_id = config.get("action_id")

    if client_id and api_key and action_id:
        try:
            logger.info("Running scheduled promo rotation...")
            run_promo_rotation(client_id, api_key, action_id)
            logger.info("Scheduled promo rotation completed.")
        except Exception as e:
            logger.error(f"Error in background rotation: {e}")
    else:
        logger.warning("Missing Ozon credentials or action_id for background rotation.")

# Initialize scheduler
scheduler = BackgroundScheduler()
# Run every 4 hours for the promo campaign rotation worker.
scheduler.add_job(func=background_rotation, trigger="interval", hours=4, id='rotation_job')
scheduler.start()

# Shut down the scheduler when exiting the app
atexit.register(lambda: scheduler.shutdown())

# Removed legacy root and actions endpoints that were clashing with the new UI

@app.route('/actions', methods=['GET'])
def get_actions():
    client_id = request.args.get('client_id')
    api_key = request.args.get('api_key')
    if not client_id or not api_key:
        return jsonify({"error": "Missing credentials"}), 400

    try:
        actions = ozon_api.get_actions(client_id, api_key)
        return jsonify(actions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/rotate', methods=['POST'])
def force_rotate():
    config = load_config()
    client_id = config.get("client_id")
    api_key = config.get("api_key")
    action_id = config.get("action_id")
    count = int(config.get("count", 5))

    if not client_id or not api_key or not action_id:
        return jsonify({"error": "Configuration is incomplete. Please save settings first."}), 400

    try:
        result = ozon_api.rotate_products(client_id, api_key, action_id, count, STATE_FILE)

        # Reset the scheduler timer since we just rotated
        job = scheduler.get_job('rotation_job')
        if job:
            # Reschedule to 4 hours from now
            scheduler.reschedule_job('rotation_job', trigger='interval', hours=4)

        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/questions', methods=['GET'])
def fetch_questions():
    config = load_config()
    client_id = config.get('client_id')
    api_key = config.get('api_key')
    openai_key = config.get('openai_api_key')

    if not client_id or not api_key:
        return jsonify({"error": "Missing Ozon credentials"}), 400

    try:
        questions_data = ozon_api.get_questions(client_id, api_key)

        # We need to map and generate draft answers
        processed_questions = []
        for q in questions_data:
            question_text = q.get('text', '')
            product_id = q.get('product_id', 'Unknown')
            question_id = q.get('id')

            draft_answer = ""
            if openai_key:
                draft_answer = llm_helper.generate_answer(question_text, product_id, openai_key)
            else:
                draft_answer = "Введите OpenAI API Key для генерации ответа."

            processed_questions.append({
                "id": question_id,
                "text": question_text,
                "product_id": product_id,
                "author": q.get('author', {}).get('first_name', 'Покупатель'),
                "draft_answer": draft_answer
            })

        return jsonify({"questions": processed_questions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/answer', methods=['POST'])
def submit_answer():
    config = load_config()
    client_id = config.get('client_id')
    api_key = config.get('api_key')

    if not client_id or not api_key:
        return jsonify({"error": "Missing Ozon credentials"}), 400

    data = request.json
    question_id = data.get('question_id')
    text = data.get('text')

    if not question_id or not text:
        return jsonify({"error": "Missing question_id or text"}), 400

    try:
        result = ozon_api.answer_question(client_id, api_key, question_id, text)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # Never run with debug=True in production. We are relying on the user to wrap this in a WSGI container.
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
