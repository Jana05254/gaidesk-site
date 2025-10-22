import os, tempfile
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db

load_dotenv()
DATABASE_URL = os.getenv("https://gaidesk-default-rtdb.asia-southeast1.firebasedatabase.app/")
API_TOKEN    = os.getenv("API_TOKEN", "JANA_FIREBASE_EDGE_2025_KEY")
PORT         = int(os.getenv("PORT", "5000"))

# خذي المفتاح من متغير بيئة (آمن على السحابة)
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON")
SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH")  # اختياري للمحلي

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

app = Flask(__name__)
CORS(app)

# ... باقي مساراتك كما هي ...

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
