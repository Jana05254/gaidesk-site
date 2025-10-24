import os, tempfile, time
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

# مفاتيح الخدمة (service account)
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH")

# -------------------------------------------------
# تهيئة Firebase Admin
# -------------------------------------------------
if SERVICE_ACCOUNT_JSON:
    # المفتاح انحفظ كسلسلة JSON في env
    fd, tmp = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SERVICE_ACCOUNT_JSON)
    cred = credentials.Certificate(tmp)

elif SERVICE_ACCOUNT_PATH and os.path.exists(SERVICE_ACCOUNT_PATH):
    # المفتاح موجود كملف على السيرفر/الديف
    cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)

else:
    raise RuntimeError("No service account provided (SERVICE_ACCOUNT_JSON or SERVICE_ACCOUNT_PATH missing)")

firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})

# -------------------------------------------------
# إعداد Flask
# -------------------------------------------------
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# لو عندنا جهاز واحد حاليا
DEFAULT_DEVICE = "GAIDESK-01"

# helper صغير للـ DB
def _ref(path="data"):
    return db.reference(path)

# -------------------------------------------------
# صفحات الواجهة (HTML)
# -------------------------------------------------
@app.route("/")
def home():
    # dashboard الرئيسية
    return render_template("index.html", title="لوحة GAIDESK")

@app.route("/devices")
def devices_page():
    # صفحة تعرض الأجهزة، ممكن تطورينها لاحقاً
    return render_template("devices.html", title="الأجهزة")

@app.route("/api-docs")
def api_docs():
    # صفحة توثيق الـ API
    return render_template("api.html", title="توثيق API")

@app.route("/about")
def about():
    # صفحة تعريف عن GAIDESK
    return render_template("about.html", title="عن GAIDESK")

# -------------------------------------------------
# REST API
# -------------------------------------------------

@app.route("/api/data")
def api_data():
    """
    هذه كانت موجودة من قبل.
    ترجع readings قديمة (historical) عشان الرسم البياني/الجدول.
    كيف تشتغل حالياً:
      ?limit=50 (افتراضي)
      ?device=GAIDESK-01 (اختياري)

    NOTE: هذا يعتمد على شكل الداتا في Realtime DB.
    في النسخة الأولى حقّك كان /data/<device>/<randomKey>...
    وفي النسخة الجديدة عندك جلسات /sessions/.../readings.
    لو تبين بعدين نعدلها نعدّلها.
    للحين بخليها كما هي حتى ما نكسر أي شيء في الرسم.
    """
    limit = max(1, min(int(request.args.get("limit", 50)), 200))
    device = request.args.get("device")  # اسم الجهاز لو فيه أكثر من جهاز

    # المنطق القديم كان ياخذ تحت "data" أو "data/<device>"
    base = "data" if not device else f"data/{device}"

    snap = _ref(base).order_by_key().limit_to_last(limit).get() or {}

    # رجعهم كقائمة مرتبة تنازلياً (الأحدث أولاً)
    items = []
    for k in sorted(snap.keys(), reverse=True):
        items.append({"key": k, "value": snap[k]})

    return jsonify(items)


@app.route("/api/devices")
def api_devices():
    """
    ترجع قائمة الأجهزة الحالية.
    نحاول استنتاج أسماء الأجهزة من تحت /data/
    """
    root = _ref("data").get() or {}

    # محاولة ذكية: لو /data/GAIDESK-01/... موجودة، نستخرج GAIDESK-01
    if isinstance(root, dict):
        names = list(root.keys())
    else:
        names = [DEFAULT_DEVICE]

    return jsonify(sorted(names))


@app.route("/api/live")
def api_live():
    """
    مهمّة جداً 👇
    ترجع آخر قراءة "فعلية الآن" من الجهاز.

    الديفايس يرفع آخر قياس إلى:
      /data/<device>/latest

    هنا نجيبها ونرجعها للواجهة.
    """
    device = request.args.get("device", DEFAULT_DEVICE)

    latest_path = f"data/{device}/latest"
    snap = _ref(latest_path).get() or {}

    # snap ممكن يكون {} لو ما في جلسة فعالة
    # بنرجع كل شيء زي ما هو، عشان الواجهة تعرضه

    return jsonify({
        "device": device,
        "data": snap
    })


@app.route("/api/post", methods=["POST"])
def api_post():
    """
    هذا الراوت للإدخال من الأجهزة لو حابة تخلي الـESP32
    يرسل عن طريق السيرفر بدل ما يكتب على Firebase مباشرة.
    (أنتِ حالياً تسوين الكتابة من ESP32 مباشرة إلى Firebase،
     فما تحتاجينه دايركت. بس نخليه هنا لأنه موجود أصلاً في شغلك)

    الاستعمال: send POST مع هيدر Authorization: Bearer TOKEN
    والبودي JSON فيه القياسات.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "missing bearer token"}), 401

    token = auth.split(" ", 1)[1].strip()
    if token != API_TOKEN:
        return jsonify({"error": "invalid token"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid json"}), 400

    # نحاول نقرأ اسم الجهاز من البودي، وإلا نستخدم الافتراضي
    device = payload.pop("device", DEFAULT_DEVICE)

    # المفتاح = timestamp بالميللي ثانية
    key = str(int(time.time() * 1000))

    # نكتب تحت /data/<device>/<key> = payload
    # (هذا كان السلوك القديم)
    ref = _ref(f"data/{device}").child(key)
    ref.set(payload)

    return jsonify({"ok": True, "device": device, "key": key})


# -------------------------------------------------
# أشياء شكلية (favicon / errors)
# -------------------------------------------------

@app.route("/favicon.ico")
def favicon():
    p = os.path.join(app.root_path, "static")
    if os.path.exists(os.path.join(p, "favicon.ico")):
        return send_from_directory(p, "favicon.ico", mimetype="image/x-icon")
    abort(404)


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html", title="غير موجود"), 404

@app.errorhandler(500)
def err500(e):
    return render_template("500.html", title="خطأ داخلي"), 500


# -------------------------------------------------
# تشغيل محلي (مو مستخدم على Render لأن Render يشغل gunicorn)
# -------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
