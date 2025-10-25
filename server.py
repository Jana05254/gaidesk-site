import os, tempfile, time, json
from flask import Flask, jsonify, request, render_template, send_from_directory, abort
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
    raise RuntimeError("No service account provided (need SERVICE_ACCOUNT_JSON or SERVICE_ACCOUNT_PATH)")

firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})

# -------------------------------------------------
# تكوين Flask
# -------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# =================================================
#                صفحات HTML
# =================================================

@app.route("/")
def landing():
    # الصفحة الرئيسية التسويقية (من landing.html)
    return render_template("landing.html", title="GAIDESK")

@app.route("/live")
def live_page():
    # المراقبة الحية من الجهاز
    return render_template("live.html", title="المراقبة الآن")

@app.route("/session")
def session_page():
    # ملخص آخر جلسة
    return render_template("session.html", title="ملخص الجلسة")

@app.route("/about")
def about_page():
    # صفحة "عن المشروع / عني"
    return render_template("about.html", title="عن GAIDESK")

# صفحة توثيق الـ API (اختياري: لو تبين تخلينه، أو ممكن تحذفين الراوت هذا)
@app.route("/api-docs")
def api_docs():
    return render_template("api.html", title="توثيق API")


# =================================================
#                دوال مساعدة
# =================================================

def _ref(path="data"):
    """اختصار للوصول الى db.reference(path)"""
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
#                REST API
# =================================================

@app.route("/api/data")
def api_data():
    """
    ترجع آخر القراءات (افتراضي 50) من المسار:
      /data/<device>/sessions/<last_session>/readings/*
    أو fallback من /data/<device>/latest
    - باراميتر:
        ?limit=25
        &device=GAIDESK-01
    شكل كل عنصر في الـ JSON:
    [
      {
        "ts": 1730000000000,  <-- timestamp من الجهاز
        "co2": 800,
        "t": 24.5,
        "F": 32,
        "bpm": 14.2,
        "dist": 52,
        "presence": 1
      },
      ...
    ]
    """
    limit = max(1, min(int(request.args.get("limit", 50)), 200))
    device = request.args.get("device", "GAIDESK-01")

    dev_ref = _ref(f"data/{device}")
    dev_data = dev_ref.get() or {}

    # نحاول ناخذ أحدث جلسة
    sessions = dev_data.get("sessions", {})
    if isinstance(sessions, dict) and sessions:
        # آخر جلسة على حسب المفتاح (المفتاح غالباً ISO timestamp)
        session_keys = sorted(sessions.keys(), reverse=True)
        last_session_key = session_keys[0]
        readings = sessions.get(last_session_key, {}).get("readings", {})
        # readings تحتها push keys (timestamps من الجهاز)
        # نقلبها لأجدد أولاً
        items = []
        for rk, payload in readings.items():
            if isinstance(payload, dict):
                # نزبط الـ timestamp:
                # لو فيه ts[".sv"]="timestamp" لازم نحاول نجيب "ts" اللي هو رقم
                ts_val = payload.get("ts")
                if isinstance(ts_val, dict):
                    ts_val = None  # هذا يعني الـ .sv من Firebase
                items.append({
                    "ts": ts_val,
                    "co2": payload.get("co2"),
                    "t": payload.get("t"),
                    "F": payload.get("F"),
                    "bpm": payload.get("bpm"),
                    "dist": payload.get("dist"),
                    "presence": payload.get("presence"),
                })
        # نفرز حسب ts (الأجدد أول)
        # لو ts مفقود نخليه 0 عشان يطلع آخر الجدول
        items.sort(key=lambda x: x["ts"] if x["ts"] else 0, reverse=True)
        items = items[:limit]

        return jsonify(items)

    # ما فيه sessions؟ نطيح على /data/<device>/latest
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
    يرجع meta لأحدث جلسة:
    {
      "session_key": "...",
      "start_iso": "2025-10-25T12:00:00Z",
      "end_iso":   "2025-10-25T13:10:00Z",
      "duration_sec": 4200,
      "alerts": {...},
      "stats":   {...}
    }
    */
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

    # نضمن مفاتيح مهمة لو ناقصة
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
    ترجع قائمة الأجهزة اللي عندنا تحت /data/*
    إذا ما قدرنا نقرأ البنية، نرجع ["GAIDESK-01"] عشان ما نكسر الواجهة
    """
    snap = _ref("data").get() or {}
    if not isinstance(snap, dict):
        return jsonify(["GAIDESK-01"])

    names = []
    for k,v in snap.items():
        # نتأكد انه dict وفيه sessions او latest (يعني شكله جهاز)
        if isinstance(v, dict) and ("sessions" in v or "latest" in v):
            names.append(k)

    if not names:
        names = ["GAIDESK-01"]

    names.sort()
    return jsonify(names)


@app.route("/api/post", methods=["POST"])
def api_post():
    """
    هذا هو الـ endpoint اللي الجهاز (ESP32) يستعمله عشان يرسل القياسات.
    الحماية: لازم Authorization: Bearer <API_TOKEN>
    الـ JSON اللي يرسله الجهاز مثلاً:
    {
      "device": "GAIDESK-01",
      "t": 24.5,
      "co2": 800,
      "F": 32,
      "bpm": 14.2,
      "dist": 52,
      "presence": 1,
      "ts": 1730000000000
    }

    احنا هنا نحفظ:
      - /data/<device>/latest        (PUT)
      - /data/<device>/sessions/<session_key>/latest (PUT)
      - /data/<device>/sessions/<session_key>/readings (POST / push)
    مع ملاحظة إن الـ ESP32 في كوده أصلاً يرسلها بنفسه مباشرة للـ Firebase.
    فهذي الراوت مفيدة لو تبغين ترسلي داتا من محاكي/اختبار.
    """

    # تحقق من التوكن
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "missing bearer token"}), 401
    if auth.split(" ", 1)[1].strip() != API_TOKEN:
        return jsonify({"error": "invalid token"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid json"}), 400

    device = payload.pop("device", "GAIDESK-01")
    # نستخدم ms timestamp كـ key فريد في readings
    key = str(int(time.time() * 1000))

    # نحط نسخة تحت /data/<device>/latest
    _ref(f"data/{device}/latest").set(payload)

    # ولو فيه session_key بالبايلود نقدر نضيفها تحت /sessions/<...>
    session_key = payload.get("session_key")
    if session_key:
        root = _session_root(device, session_key)

        # latest في الجلسة
        _ref(root["latest"]).set(payload)

        # readings (push-like)
        _ref(root["readings"]).child(key).set(payload)

    return jsonify({"ok": True, "device": device, "key": key})


# =================================================
#               Static Extras
# =================================================

@app.route("/favicon.ico")
def favicon():
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
    # host=0.0.0.0 عشان يشتغل على Render / Ngrok / أي سيرفر عام
    app.run(host="0.0.0.0", port=PORT, debug=False)
