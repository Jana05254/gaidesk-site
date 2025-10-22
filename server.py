import os, tempfile, json, time
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db

load_dotenv()

# اقرأ القيم من المتغيرات (لا تحطيها ثابتة في الكود)
DATABASE_URL = os.getenv("DATABASE_URL")
API_TOKEN    = os.getenv("API_TOKEN", "CHANGE_ME_32CHARS")
PORT         = int(os.getenv("PORT", "5000"))

# مفتاح الخدمة: من متغير بيئة في السحابة أو من ملف محلي للتجربة
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH")  # محلي فقط (اختياري)

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

app = Flask(__name__, template_folder="templates")
CORS(app)

# الصفحة الرئيسية
@app.route("/")
def home():
    return render_template("index.html")

# قراءة آخر البيانات
@app.route("/api/data")
def api_data():
    ref = db.reference("data")
    snap = ref.order_by_key().limit_to_last(50).get() or {}
    items = []
    # نحوّل القاموس إلى قائمة مرتبة تنازلياً بالمفتاح
    for k in sorted(snap.keys(), reverse=True):
        items.append({"key": k, "value": snap[k]})
    return jsonify(items)

# كتابة (محمي بتوكن Bearer)
@app.route("/api/post", methods=["POST"])
def api_post():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "missing bearer token"}), 401
    token = auth.split(" ", 1)[1].strip()
    if token != API_TOKEN:
        return jsonify({"error": "invalid token"}), 403

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid json"}), 400

    # مفتاح تلقائي (مثلاً طابع زمني)
    key = str(int(time.time() * 1000))
    db.reference("data").child(key).set(payload)
    return jsonify({"ok": True, "key": key})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
