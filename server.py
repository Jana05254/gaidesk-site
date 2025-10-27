import os, tempfile, time, json
from flask import Flask, jsonify, request, render_template, send_from_directory, abort
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db

# ---------------- إعداد المتغيرات ----------------
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
API_TOKEN    = os.getenv("API_TOKEN", "CHANGE_ME_32CHARS")
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
    raise RuntimeError("No service account provided (need SERVICE_ACCOUNT_JSON or SERVICE_ACCOUNT_PATH)")

firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})

# ---------------- Flask setup ----------------
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# ==========================================================
#                       صفحات الموقع
# ==========================================================

@app.route("/")
def landing():
    return render_template("landing.html", title="GAIDESK")

@app.route("/dashboard")
def devices_page():
    return render_template("devices.html", title="لوحة المراقبة")

@app.route("/session")
def session_page():
    return render_template("session.html", title="ملخص الجلسة")

@app.route("/about")
def about_page():
    return render_template("about.html", title="عن GAIDESK")

@app.route("/api-docs")
def api_docs():
    return render_template("api.html", title="توثيق API")

# ==========================================================
#                      Firebase helpers
# ==========================================================

def _ref(path="data"):
    return db.reference(path)

def _session_root(device_id: str, session_key: str):
    base = f"data/{device_id}/sessions/{session_key}"
    return {
        "base": base,
        "latest": base + "/latest",
        "meta": base + "/meta",
        "readings": base + "/readings",
    }

# ==========================================================
#                      REST API
# ==========================================================

@app.route("/api/data")
def api_data():
    limit = max(1, min(int(request.args.get("limit", 50)), 200))
    device = request.args.get("device", "GAIDESK-01")

    dev_ref = _ref(f"data/{device}")
    dev_data = dev_ref.get() or {}
    sessions = dev_data.get("sessions", {})

    if isinstance(sessions, dict) and sessions:
        session_keys = sorted(sessions.keys(), reverse=True)
        last_session_key = session_keys[0]
        readings = sessions.get(last_session_key, {}).get("readings", {})
        items = []
        for rk, payload in readings.items():
            if isinstance(payload, dict):
                ts_val = payload.get("ts")
                if isinstance(ts_val, dict): ts_val = None
                items.append({
                    "ts": ts_val,
                    "co2": payload.get("co2"),
                    "t": payload.get("t"),
                    "F": payload.get("F"),
                    "bpm": payload.get("bpm"),
                    "dist": payload.get("dist"),
                    "presence": payload.get("presence"),
                })
        items.sort(key=lambda x: x["ts"] if x["ts"] else 0, reverse=True)
        return jsonify(items[:limit])

    latest_payload = dev_data.get("latest", {})
    if isinstance(latest_payload, dict) and latest_payload:
        ts_val = latest_payload.get("ts")
        if isinstance(ts_val, dict): ts_val = None
        return jsonify([{
            "ts": ts_val,
            "co2": latest_payload.get("co2"),
            "t": latest_payload.get("t"),
            "F": latest_payload.get("F"),
            "bpm": latest_payload.get("bpm"),
            "dist": latest_payload.get("dist"),
            "presence": latest_payload.get("presence"),
        }])

    return jsonify([])

@app.route("/api/devices")
def api_devices():
    snap = _ref("data").get() or {}
    if not isinstance(snap, dict):
        return jsonify(["GAIDESK-01"])
    names = [k for k, v in snap.items() if isinstance(v, dict) and ("sessions" in v or "latest" in v)]
    return jsonify(names or ["GAIDESK-01"])

# ==========================================================
#                   Error Pages
# ==========================================================
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html", title="غير موجود"), 404

@app.errorhandler(500)
def err500(e):
    return render_template("500.html", title="خطأ داخلي"), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
