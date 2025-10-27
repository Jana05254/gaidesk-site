import os, tempfile, time
from datetime import datetime
from flask import (
    Flask,
    jsonify,
    request,
    render_template,
    send_from_directory,
    abort,
    redirect,
    url_for,
)
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db


# -------------------------------------------------
# تحميل المتغيرات من .env
# -------------------------------------------------
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
API_TOKEN    = os.getenv("API_TOKEN", "CHANGE_ME_32CHARS")
PORT         = int(os.getenv("PORT", "5000"))

# مفاتيح Firebase Admin
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH")

if SERVICE_ACCOUNT_JSON:
    # في حال انك حاطة الـ JSON كامل داخل env كسطر
    fd, tmp = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SERVICE_ACCOUNT_JSON)
    cred = credentials.Certificate(tmp)
elif SERVICE_ACCOUNT_PATH and os.path.exists(SERVICE_ACCOUNT_PATH):
    # في حال عندك ملف JSON فعلي على السيرفر
    cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
else:
    raise RuntimeError(
        "No service account provided (need SERVICE_ACCOUNT_JSON or SERVICE_ACCOUNT_PATH)"
    )

firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})


# -------------------------------------------------
# تهيئة Flask
# -------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)


# -------------------------------------------------
# متغيرات مشتركة (مثلاً السنة عشان حقوق الفوتر)
# -------------------------------------------------
@app.context_processor
def inject_globals():
    return {
        "current_year": datetime.utcnow().year
    }


# =================================================
#                صفحات HTML (Routing)
# =================================================

@app.route("/")
def home_page():
    """
    الصفحة الرئيسية البسيطة:
    - لوقو GAIDESK كبير
    - "ابدأ المراقبة الآن"
    - "تعرف على GAIDESK"
    """
    return render_template("index.html", title="GAIDESK")


@app.route("/dashboard")
def dashboard_page():
    """
    شاشة المراقبة الفعلية (قلب المنتج)
    تعرض آخر قراءة، حالة الجلسة، التنبيه، والجدول
    """
    return render_template("devices.html", title="المراقبة الآن")


@app.route("/about")
def about_page():
    """
    صفحة عن GAIDESK:
    - مين يحتاجه
    - ليش مفيد
    - مين صمّمه
    """
    return render_template("about.html", title="عن GAIDESK")


@app.route("/session")
def session_page():
    """
    (اختياري) صفحة ملخص جلسة/جلسات سابقة أو آخر جلسة من Firebase
    لو ما تبينها، تقدرين تشيلينها من الناف بار
    """
    return render_template("session.html", title="ملخص الجلسة")


# أي روابط قديمة مثل /landing أو /live نحولها للروابط الجديدة
@app.route("/landing")
def legacy_landing_redirect():
    # أي أحد يزور /landing ياخذه للصفحة الرئيسية الجديدة
    return redirect(url_for("home_page"), code=302)

@app.route("/live")
def legacy_live_redirect():
    # live القديمة صارت dashboard
    return redirect(url_for("dashboard_page"), code=302)


# =================================================
#                دوال مساعدة
# =================================================

def _ref(path="data"):
    """اختصار للوصول إلى db.reference(path)"""
    return db.reference(path)

def _session_root(device_id: str, session_key: str):
    """
    يرجّع المسارات الكاملة لجلسة وحدة داخل الـ Realtime DB:
    /data/<device>/sessions/<session_key>/{latest,meta,readings}
    """
    base = f"data/{device_id}/sessions/{session_key}"
    return {
        "base": base,
        "latest": base + "/latest",
        "meta": base + "/meta",
        "readings": base + "/readings",
    }


# =================================================
#                REST API (Frontend uses these)
# =================================================

@app.route("/api/data")
def api_data():
    """
    ترجع آخر القراءات من أحدث جلسة، أو fallback على /latest
    باراميترز:
      ?limit=25
      &device=GAIDESK-01
    الإخراج: list of dicts (أجدد أول عنصر)
    """
    limit = max(1, min(int(request.args.get("limit", 50)), 200))
    device = request.args.get("device", "GAIDESK-01")

    dev_ref = _ref(f"data/{device}")
    dev_data = dev_ref.get() or {}

    # جرّبي تجيبي أحدث جلسة
    sessions = dev_data.get("sessions", {})
    if isinstance(sessions, dict) and sessions:
        session_keys = sorted(sessions.keys(), reverse=True)
        last_session_key = session_keys[0]

        readings = sessions.get(last_session_key, {}).get("readings", {})
        items = []
        for rk, payload in readings.items():
            if not isinstance(payload, dict):
                continue

            # ts ممكن يكون dict لو هو {".sv": "timestamp"}, نفلتره
            ts_val = payload.get("ts")
            if isinstance(ts_val, dict):
                ts_val = None

            items.append({
                "ts": ts_val,
                "co2": payload.get("co2"),
                "t": payload.get("t"),
                "F": payload.get("F"),
                "bpm": payload.get("bpm"),
                "dist": payload.get("dist"),
                "presence": payload.get("presence"),
            })

        # الأجدد أول
        items.sort(key=lambda x: x["ts"] if x["ts"] else 0, reverse=True)
        items = items[:limit]
        return jsonify(items)

    # ما فيه جلسات؟ نطيح على /latest فقط
    latest_payload = dev_data.get("latest", {})
    if isinstance(latest_payload, dict) and latest_payload:
        ts_val = latest_payload.get("ts")
        if isinstance(ts_val, dict):
            ts_val = None

        item = {
            "ts": ts_val,
            "co2": latest_payload.get("co2"),
            "t": latest_payload.get("t"),
            "F": latest_payload.get("F"),
            "bpm": latest_payload.get("bpm"),
            "dist": latest_payload.get("dist"),
            "presence": latest_payload.get("presence"),
        }
        return jsonify([item])

    # لا جلسة ولا latest
    return jsonify([])


@app.route("/api/session-summary")
def api_session_summary():
    """
    يرجّع meta لأحدث جلسة
    {
      "device": "GAIDESK-01",
      "session_key": "...",
      "start_iso": "...",
      "end_iso": "...",
      "duration_sec": ...,
      "status": "...",
      "alerts": {...},
      "stats": {...},
      "final_state": "SUMMARY" | "ACTIVE" | ...
    }
    """
    device = request.args.get("device", "GAIDESK-01")

    dev_ref = _ref(f"data/{device}")
    dev_data = dev_ref.get() or {}
    sessions = dev_data.get("sessions", {})

    if not (isinstance(sessions, dict) and sessions):
        return jsonify({"error": "no sessions"}), 404

    session_keys = sorted(sessions.keys(), reverse=True)
    last_key = session_keys[0]
    meta = sessions.get(last_key, {}).get("meta", {})

    resp = {
        "device": device,
        "session_key": last_key,
        "start_iso": meta.get("start_iso"),
        "end_iso": meta.get("end_iso"),
        "duration_sec": meta.get("duration_sec"),
        "status": meta.get("status"),
        "alerts": meta.get("alerts", {}),
        "stats":  meta.get("stats", {}),
        "final_state": meta.get("final_state"),
    }
    return jsonify(resp)


@app.route("/api/devices")
def api_devices():
    """
    يرجّع قائمة الأجهزة تحت /data/*
    إذا البنية مو واضحة نرجع ["GAIDESK-01"] بدل ما نعطل الصفحة
    """
    snap = _ref("data").get() or {}
    if not isinstance(snap, dict):
        return jsonify(["GAIDESK-01"])

    names = []
    for k, v in snap.items():
        if isinstance(v, dict) and ("sessions" in v or "latest" in v):
            names.append(k)

    if not names:
        names = ["GAIDESK-01"]

    names.sort()
    return jsonify(names)


@app.route("/api/post", methods=["POST"])
def api_post():
    """
    Endpoint استقبال قراءات من الجهاز (لو احتجتيه للاختبار).
    حماية بالتوكن:
      Authorization: Bearer <API_TOKEN>
    JSON example:
    {
      "device": "GAIDESK-01",
      "t": 24.5,
      "co2": 800,
      "F": 32,
      "bpm": 14.2,
      "dist": 52,
      "presence": 1,
      "ts": 1730000000000,
      "session_key": "2025-10-25T12-00-00Z"
    }
    يكتب:
      /data/<device>/latest
    ولو فيه session_key يكتب كمان:
      /data/<device>/sessions/<session_key>/latest
      /data/<device>/sessions/<session_key>/readings/<pushKey>
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "missing bearer token"}), 401
    if auth.split(" ", 1)[1].strip() != API_TOKEN:
        return jsonify({"error": "invalid token"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid json"}), 400

    device = payload.get("device", "GAIDESK-01")
    session_key = payload.get("session_key")

    # push key based on current server time
    push_key = str(int(time.time() * 1000))

    # latest للجهاز
    _ref(f"data/{device}/latest").set(payload)

    # لو فيه session_key نكتب في الجلسة
    if session_key:
        root = _session_root(device, session_key)

        # latest في الجلسة
        _ref(root["latest"]).set(payload)

        # readings (push-like)
        _ref(root["readings"]).child(push_key).set(payload)

    return jsonify({"ok": True, "device": device, "key": push_key})


# =================================================
#               Static Extras
# =================================================

@app.route("/favicon.ico")
def favicon():
    """
    يرجّع favicon.ico لو موجود تحت static/
    """
    p = os.path.join(app.root_path, "static")
    ico_path = os.path.join(p, "favicon.ico")
    if os.path.exists(ico_path):
        return send_from_directory(p, "favicon.ico", mimetype="image/x-icon")
    abort(404)


# =================================================
#               Error handlers
# =================================================

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html", title="غير موجود"), 404

@app.errorhandler(500)
def err500(e):
    return render_template("500.html", title="خطأ داخلي"), 500


# =================================================
#               تشغيل السيرفر
# =================================================

if __name__ == "__main__":
    # host=0.0.0.0 عشان يشتغل على Render / Ngrok وغيره
    app.run(host="0.0.0.0", port=PORT, debug=False)
