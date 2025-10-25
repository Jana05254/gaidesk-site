import os
import tempfile
import time
from flask import Flask, jsonify, request, render_template, send_from_directory, abort
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db

# -------------------------------------------------
# تحميل المتغيرات من .env (DATABASE_URL , SERVICE_ACCOUNT_JSON ... )
# -------------------------------------------------
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
API_TOKEN    = os.getenv("API_TOKEN", "CHANGE_ME_32CHARS")
PORT         = int(os.getenv("PORT", "5000"))

# مفاتيح Firebase
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH")

if SERVICE_ACCOUNT_JSON:
    # لو المفتاح جاي كسلسلة JSON في البيئة
    fd, tmp = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SERVICE_ACCOUNT_JSON)
    cred = credentials.Certificate(tmp)
elif SERVICE_ACCOUNT_PATH and os.path.exists(SERVICE_ACCOUNT_PATH):
    # لو المفتاح محفوظ كملف في السيرفر/المشروع
    cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
else:
    raise RuntimeError("No service account provided")

firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})

# -------------------------------------------------
# تهيئة Flask
# -------------------------------------------------
app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)
CORS(app)

# -------------------------------------------------
# أدوات مساعدة داخلية
# -------------------------------------------------
def _ref(path="data"):
    """Shortcut لعمل db.reference"""
    return db.reference(path)

def _list_sessions_for_device(device_id: str):
    """
    يرجّع كل الجلسات المسجلة لهذا الجهاز من:
    /data/<device_id>/sessions
    الشكل المتوقع:
    {
      "2025-10-25T12-34-11Z": {
         "meta": {...},
         "latest": {...},
         "readings": {...}
      },
      "2025-10-25T11-00-00Z": { ... },
      ...
    }
    """
    base = f"data/{device_id}/sessions"
    snap = _ref(base).get() or {}
    if not isinstance(snap, dict):
        snap = {}
    return snap

def _pick_latest_session_key(sessions_dict: dict):
    """
    ناخذ آخر جلسة (أحدث مفتاح) بناء على ترتيب مقلوب.
    مفاتيحك أصلاً معمولة بصيغة وقت ISO-like,
    فـ sort(reverse=True) يعطي الأحدث أولاً.
    """
    if not sessions_dict:
        return None
    keys_sorted = sorted(sessions_dict.keys(), reverse=True)
    return keys_sorted[0] if keys_sorted else None


# -------------------------------------------------
# صفحات الموقع (front-end)
# -------------------------------------------------

@app.route("/")
def home():
    """
    الصفحة الرئيسية: داشبورد مباشر للبيانات الحيّة.
    لازم يكون عندك templates/index.html
    """
    return render_template("index.html", title="لوحة GAIDESK")

@app.route("/session")
def session_page():
    """
    صفحة ملخص آخر جلسة.
    لازم يكون عندك templates/session.html
    """
    return render_template("session.html", title="ملخص الجلسة")

@app.route("/about")
def about_page():
    """
    صفحة تعريف بالمنتج.
    لازم يكون عندك templates/about.html
    """
    return render_template("about.html", title="عن GAIDESK")

# -------------------------------------------------
# REST API
# -------------------------------------------------

@app.route("/api/data")
def api_data():
    """
    يعيد آخر القراءات (افتراضي 50).
    باراميترات (اختيارية):
      ?limit=25
      ?device=GAIDESK-01

    الهدف: هذه الداتا تروح للواجهة الرئيسية (index.html)
    عشان:
    - نعرض وجود المستخدم
    - F (الإجهاد)
    - CO₂
    - الحرارة
    - المسافة
    - الخ...

    ملاحظة مهمة:
    الـ ESP32 يحفظ القراءات داخل:
      /data/<device>/sessions/<sessionKey>/readings/<timestamp> : {...}
    فإحنا بناخذ "آخر جلسة" لهذا الجهاز ونرجع القراءات من هناك.
    """
    # كم عنصر نبغى
    limit = request.args.get("limit", "50")
    try:
        limit = int(limit)
    except:
        limit = 50
    limit = max(1, min(limit, 200))

    # أي جهاز؟
    device_id = request.args.get("device", "GAIDESK-01")

    # نجيب كل الجلسات الخاصة بهذا الجهاز
    sessions_dict = _list_sessions_for_device(device_id)

    # إذا مافي جلسات -> رجعي مصفوفة فاضية
    if not sessions_dict:
        return jsonify([])

    # اختاري آخر جلسة
    last_key = _pick_latest_session_key(sessions_dict)
    if not last_key:
        return jsonify([])

    last_session = sessions_dict.get(last_key, {})
    readings = last_session.get("readings", {})

    # structure المتوقع:
    # readings = {
    #   "1698956278532": {
    #       "t": 25.8,
    #       "co2": 500,
    #       "F": 32,
    #       "presence": 1,
    #       "bpm": 18.4,
    #       "dist": 50,
    #       "session_start_ts": 1700000000000,
    #       "ts": {".sv": "timestamp"}  <-- أو timestamp فعلي لو ESP هو اللي حطّه
    #   },
    #   ...
    # }

    # نرتب بالمفتاح (timestamps كـ string) تنازليًا
    # ثم نقص limit
    items = []
    if isinstance(readings, dict):
        for k in sorted(readings.keys(), reverse=True):
            v = readings[k] or {}
            # نوحّد الـtimestamp
            # لو فيه ts كرقم جاهز (ms) خليه، لو ما فيه بنحاول ناخذ k
            ts_val = None
            raw_ts = v.get("ts")
            # أحياناً ts يكون dict { ".sv": "timestamp" } -> ما ينفع
            if isinstance(raw_ts, (int, float)):
                ts_val = int(raw_ts)
            else:
                # جرّبي نقلب المفتاح نفسه إلى int
                try:
                    ts_val = int(k)
                except:
                    ts_val = None

            items.append({
                "key": k,
                "value": {
                    "ts": ts_val,
                    "co2": v.get("co2"),
                    "t": v.get("t"),
                    "F": v.get("F"),
                    "presence": v.get("presence"),
                    "bpm": v.get("bpm"),
                    "dist": v.get("dist"),
                    # نخلي session_start_ts لو ودك تعرضينه لاحقاً
                    "session_start_ts": v.get("session_start_ts"),
                }
            })

    # خذي فقط limit
    items = items[:limit]

    return jsonify(items)


@app.route("/api/session-summary")
def api_session_summary():
    """
    يرجع meta لأحدث جلسة منتهية/موجودة.
    هذه الداتا تُستخدم في صفحة /session لعرض الملخص.

    ESP32 يرسل meta هنا:
      /data/<device>/sessions/<sessionKey>/meta

    شكل meta (من الكود حقك):
    {
      "start_ts": <ms>,
      "start_iso": "...",
      "end_ts": <ms>,
      "end_iso": "...",
      "duration_sec": 1234,
      "alerts": {
        "near":  0,
        "co2":   0,
        "warn1": 0,
        "warn2": 0
      },
      "stats": {
        "dist": { "min":..,"avg":..,"max":.. },
        "co2":  {...},
        "temp": {...},
        "risk": {...},
        "F":    {...},
        "bpm":  {...}
      },
      "device": "GAIDESK-01",
      "final_state": "SUMMARY",
      "session_key": "2025-10-25T12-34-11Z",
      "status": "ended",
      "updated_ts": {".sv": "timestamp"}
    }
    """
    device_id = request.args.get("device", "GAIDESK-01")

    # احصل على كل الجلسات
    sessions_dict = _list_sessions_for_device(device_id)
    if not sessions_dict:
        return jsonify({"error": "no sessions", "device": device_id}), 404

    # خذ آخر جلسة
    latest_key = _pick_latest_session_key(sessions_dict)
    if not latest_key:
        return jsonify({"error": "no session key", "device": device_id}), 404

    session_node = sessions_dict.get(latest_key, {})
    meta = session_node.get("meta", {})

    # لو مافي meta -> نرجع info بسيط
    if not meta:
        return jsonify({
            "device": device_id,
            "session_key": latest_key,
            "error": "no meta"
        })

    # انسخي الـ meta نفسه + session_key + device
    meta_out = dict(meta)
    meta_out["device"] = device_id
    meta_out["session_key"] = latest_key

    # زيادة سلامة: duration_sec لو مو موجودة
    if "duration_sec" not in meta_out:
        # نحاول نحسبها لو فيه start_ts/end_ts بالميلي ثانية
        st_ms = meta_out.get("start_ts")
        en_ms = meta_out.get("end_ts")
        if isinstance(st_ms, (int, float)) and isinstance(en_ms, (int, float)):
            dur_s = int( (en_ms - st_ms) / 1000 )
        else:
            dur_s = None
        meta_out["duration_sec"] = dur_s

    return jsonify(meta_out)


@app.route("/api/post", methods=["POST"])
def api_post():
    """
    (نفس الفكرة الأصلية)
    يستقبل قراءة من الجهاز (ESP32) باستخدام Bearer token.
    يخزنها في Firebase.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "missing bearer token"}), 401
    if auth.split(" ", 1)[1].strip() != API_TOKEN:
        return jsonify({"error": "invalid token"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid json"}), 400

    # الجهاز المرسل
    device = payload.pop("device", "GAIDESK-01")
    # نخزن القراءة تحت data/<device>/{timestamp}:payload
    key = str(int(time.time() * 1000))

    _ref(f"data/{device}").child(key).set(payload)

    return jsonify({"ok": True, "device": device, "key": key})


# -------------------------------------------------
# ملفات ثابتة (favicon) + أخطاء
# -------------------------------------------------

@app.route("/favicon.ico")
def favicon():
    p = os.path.join(app.root_path, "static")
    ico_path = os.path.join(p, "favicon.ico")
    if os.path.exists(ico_path):
        return send_from_directory(p, "favicon.ico", mimetype="image/x-icon")
    abort(404)

@app.errorhandler(404)
def not_found(e):
    # صفحة 404 بسيطة (لو حبيتي تعملي 404.html لاحقاً)
    return render_template("404.html", title="غير موجود") if os.path.exists(os.path.join(app.template_folder,"404.html")) \
        else ("الصفحة غير موجودة", 404)

@app.errorhandler(500)
def err500(e):
    return render_template("500.html", title="خطأ داخلي") if os.path.exists(os.path.join(app.template_folder,"500.html")) \
        else ("خطأ داخلي في السيرفر", 500)

# -------------------------------------------------
# تشغيل محلي
# -------------------------------------------------
if __name__ == "__main__":
    # على جهازك المحلي:
    # http://localhost:5000
    app.run(host="0.0.0.0", port=PORT, debug=False)
