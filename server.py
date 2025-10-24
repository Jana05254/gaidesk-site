import os, tempfile, time, json
from flask import Flask, jsonify, request, render_template, send_from_directory, abort
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db

load_dotenv()

# إعداد المتغيرات
DATABASE_URL = os.getenv("DATABASE_URL")
API_TOKEN    = os.getenv("API_TOKEN", "GAIDESK_EDGE_KEY")
PORT         = int(os.getenv("PORT", "5000"))

SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH")

if SERVICE_ACCOUNT_JSON:
    fd, tmp = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SERVICE_ACCOUNT_JSON)
    cred = credentials.Certificate(tmp)
elif SERVICE_ACCOUNT_PATH and os.path.exists(SERVICE_ACCOUNT_PATH):
    cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
else:
    raise RuntimeError("No service account provided")

firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# ---------------- صفحات ----------------
@app.route("/")
def home():
    return render_template("index.html", title="لوحة GAIDESK")

@app.route("/alerts")
def alerts_page():
    return render_template("alerts.html", title="إعدادات التنبيه")

@app.route("/devices")
def devices_page():
    return render_template("devices.html", title="الأجهزة")

@app.route("/api-docs")
def api_docs():
    return render_template("api.html", title="توثيق API")

@app.route("/about")
def about():
    return render_template("about.html", title="عن GAIDESK")

# ---------------- إعدادات التنبيه ----------------
SETTINGS_PATH = "users/demo/settings"
DEFAULT_SETTINGS = {
    "posture_sensitivity": "Medium",
    "breath_sensitivity": "Medium",
    "stage_threshold": 0.7,
    "force_break_at": 1.0
}

def _ref(path="data"):
    return db.reference(path)

@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    ref = _ref(SETTINGS_PATH)
    if request.method == "GET":
        data = ref.get() or {}
        out = DEFAULT_SETTINGS.copy()
        out.update({k: v for k, v in (data or {}).items() if k in DEFAULT_SETTINGS})
        return jsonify(out)

    payload = request.get_json(silent=True) or {}
    stage = float(payload.get("stage_threshold", DEFAULT_SETTINGS["stage_threshold"]))
    force = float(payload.get("force_break_at", DEFAULT_SETTINGS["force_break_at"]))
    stage = min(max(stage, 0.1), 0.95)
    force = min(max(force, 0.5), 1.0)
    save_obj = {
        "posture_sensitivity": payload.get("posture_sensitivity", DEFAULT_SETTINGS["posture_sensitivity"]),
        "breath_sensitivity": payload.get("breath_sensitivity", DEFAULT_SETTINGS["breath_sensitivity"]),
        "stage_threshold": stage,
        "force_break_at": force,
    }
    ref.update(save_obj)
    return jsonify({"ok": True, "settings": save_obj})

# ---------------- API البيانات ----------------
@app.route("/api/data")
def api_data():
    limit = max(1, min(int(request.args.get("limit", 50)), 200))
    device = request.args.get("device")
    base = "data" if not device else f"data/{device}"
    snap = _ref(base).order_by_key().limit_to_last(limit).get() or {}
    items = [{"key": k, "value": snap[k]} for k in sorted(snap.keys(), reverse=True)]
    return jsonify(items)

@app.route("/api/devices")
def api_devices():
    snap = _ref("data").get() or {}
    names = sorted(list(snap.keys())) if isinstance(snap, dict) else []
    return jsonify(names)

@app.route("/api/post", methods=["POST"])
def api_post():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "missing bearer token"}), 401
    if auth.split(" ", 1)[1].strip() != API_TOKEN:
        return jsonify({"error": "invalid token"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid json"}), 400

    device = payload.pop("device", "GAIDESK-01")
    key = str(int(time.time() * 1000))
    _ref(f"data/{device}").child(key).set(payload)
    return jsonify({"ok": True, "device": device, "key": key})

# ---------------- أخطاء ----------------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html", title="غير موجود"), 404

@app.errorhandler(500)
def err500(e):
    return render_template("500.html", title="خطأ داخلي"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
