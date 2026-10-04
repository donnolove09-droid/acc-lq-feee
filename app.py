from flask import Flask, render_template, request, jsonify
import os
import json
import random
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "QD_STORE_2025_CHANGE_ME")

# ============ CẤU HÌNH TỪ ENV ============
SHOP_NAME = os.environ.get("SHOP_NAME", "QD STORE").strip()
SHOP_AVATAR = os.environ.get("SHOP_AVATAR", "").strip()
SHOP_DESCRIPTION = os.environ.get("SHOP_DESCRIPTION", "Share Acc Liên Quân Uy Tín").strip()

TELEGRAM_USERNAME = os.environ.get("TELEGRAM_USERNAME", "thelightasean").strip().replace("@", "")
TELEGRAM_LINK = f"https://t.me/{TELEGRAM_USERNAME}"

MISSION_LINK = os.environ.get("MISSION_LINK", "https://t.me/thelightasean").strip()

KEY_PRICE = os.environ.get("KEY_PRICE", "5.000đ").strip()
ACCS_PER_KEY = int(os.environ.get("ACCS_PER_KEY", "10"))

ACCOUNTS_DIR = "accounts"


# ============ SUPABASE (PostgreSQL) - psycopg 3 ============
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# psycopg 3 chấp nhận cả postgresql:// và postgres://
PG_URL = DATABASE_URL

DB_READY = False
_memory_used_keys = {}  # fallback nếu không có DB


def init_db():
    """Tạo bảng used_keys nếu chưa có"""
    global DB_READY
    if not PG_URL:
        print("[WARN] DATABASE_URL chưa set — dùng memory fallback!")
        return False

    try:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(PG_URL, row_factory=dict_row, connect_timeout=15) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS used_keys (
                        key VARCHAR(100) PRIMARY KEY,
                        used_at TIMESTAMP DEFAULT NOW(),
                        accounts JSONB
                    )
                """)
            conn.commit()

        print("[INFO] Supabase: Kết nối thành công!")
        DB_READY = True
        return True
    except Exception as e:
        print(f"[ERROR] Supabase kết nối lỗi: {e}")
        DB_READY = False
        return False


def get_conn():
    """Tạo kết nối mới đến Supabase"""
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(PG_URL, row_factory=dict_row, connect_timeout=15)


def key_used(key):
    """Check key đã dùng chưa"""
    if not DB_READY:
        return key in _memory_used_keys

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM used_keys WHERE key = %s", (key,))
                return cur.fetchone() is not None
    except Exception as e:
        print(f"[ERROR] key_used: {e}")
        return False


def mark_key_used(key, accounts):
    """Đánh dấu key đã dùng + lưu 10 acc"""
    if not DB_READY:
        _memory_used_keys[key] = {
            "used_at": datetime.now().isoformat(),
            "accounts": accounts
        }
        return

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO used_keys (key, used_at, accounts)
                    VALUES (%s, NOW(), %s::jsonb)
                    ON CONFLICT (key) DO UPDATE
                    SET used_at = NOW(), accounts = EXCLUDED.accounts
                """, (key, json.dumps(accounts)))
            conn.commit()
    except Exception as e:
        print(f"[ERROR] mark_key_used: {e}")


def get_cached_accounts(key):
    """Lấy 10 acc cũ đã random cho key"""
    if not DB_READY:
        info = _memory_used_keys.get(key)
        return info.get("accounts", []) if info else None

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT accounts FROM used_keys WHERE key = %s", (key,))
                row = cur.fetchone()
                return row["accounts"] if row else None
    except Exception as e:
        print(f"[ERROR] get_cached_accounts: {e}")
        return None


# Khởi tạo DB khi import
init_db()


# ============ ENV: API_KEY ============
def get_api_keys():
    """Lấy toàn bộ key từ ENV API_KEY"""
    raw = os.environ.get("API_KEY", "").strip()
    if not raw:
        return []

    raw = raw.replace("\r", "")
    keys = []
    for line in raw.split("\n"):
        for k in line.split(","):
            k = k.strip()
            if k:
                keys.append(k)

    # Loại trùng
    seen = set()
    unique = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


def key_valid(key):
    return key in get_api_keys()


# ============ LOAD ACCOUNTS (TỰ ĐỘNG LOẠI TRÙNG) ============
def parse_account_line(line):
    line = line.strip()
    if not line:
        return None

    if "|" in line:
        parts = line.split("|")
        if len(parts) >= 2:
            user = parts[0].strip()
            pwd = parts[1].strip()
            if user and pwd and len(user) > 1 and len(pwd) > 1:
                return {"user": user, "pass": pwd}

    if ":" in line:
        main_part = line.split("|")[0].strip()
        if ":" in main_part:
            user, pwd = main_part.split(":", 1)
            user = user.strip()
            pwd = pwd.strip()
            if user and pwd and len(user) > 1 and len(pwd) > 1:
                return {"user": user, "pass": pwd}

    return None


def load_accounts():
    accounts = []
    seen = set()
    total = 0

    if not os.path.exists(ACCOUNTS_DIR):
        print(f"[WARN] Folder {ACCOUNTS_DIR} không tồn tại!")
        return accounts

    files = sorted([f for f in os.listdir(ACCOUNTS_DIR) if f.endswith(".txt")])
    print(f"[INFO] {len(files)} file acc: {files}")

    for fname in files:
        fpath = os.path.join(ACCOUNTS_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    total += 1
                    acc = parse_account_line(line)
                    if not acc:
                        continue
                    k = acc["user"].lower()
                    if k in seen:
                        continue
                    seen.add(k)
                    accounts.append(acc)
        except Exception as e:
            print(f"[ERROR] {fname}: {e}")

    print(f"[INFO] Đọc {total} dòng → {len(accounts)} acc unique")
    return accounts


_ACCOUNTS_CACHE = None


def get_all_accounts():
    global _ACCOUNTS_CACHE
    if _ACCOUNTS_CACHE is None:
        _ACCOUNTS_CACHE = load_accounts()
    return _ACCOUNTS_CACHE


# ============ ROUTES ============
@app.route("/")
def index():
    return render_template("index.html",
                           shop_name=SHOP_NAME,
                           shop_avatar=SHOP_AVATAR,
                           shop_description=SHOP_DESCRIPTION,
                           telegram_link=TELEGRAM_LINK,
                           telegram_username=TELEGRAM_USERNAME,
                           mission_link=MISSION_LINK,
                           key_price=KEY_PRICE,
                           total_accounts=len(get_all_accounts()))


@app.route("/get_acc")
def get_acc_page():
    return render_template("get_acc.html",
                           shop_name=SHOP_NAME,
                           shop_avatar=SHOP_AVATAR,
                           telegram_link=TELEGRAM_LINK,
                           telegram_username=TELEGRAM_USERNAME,
                           key_price=KEY_PRICE)


@app.route("/api/check_key", methods=["POST"])
def api_check_key():
    """API: nhận key → check hợp lệ → random 10 acc"""
    data = request.get_json() or {}
    key = data.get("key", "").strip()

    if not key:
        return jsonify({"success": False, "message": "Vui lòng nhập key!"})

    if not key_valid(key):
        return jsonify({
            "success": False,
            "message": "❌ Key không hợp lệ! Vui lòng kiểm tra lại hoặc liên hệ Telegram để mua key."
        })

    if key_used(key):
        cached = get_cached_accounts(key)
        if cached:
            return jsonify({
                "success": True,
                "accounts": cached,
                "cached": True,
                "message": "Key này đã được sử dụng - hiển thị lại 10 acc cũ của bạn."
            })
        return jsonify({
            "success": False,
            "message": "❌ Key này đã được sử dụng!"
        })

    all_accounts = get_all_accounts()
    if len(all_accounts) < ACCS_PER_KEY:
        return jsonify({
            "success": False,
            "message": "⚠️ Kho acc đang bảo trì, vui lòng thử lại sau!"
        })

    picked = random.sample(all_accounts, ACCS_PER_KEY)
    mark_key_used(key, picked)

    return jsonify({
        "success": True,
        "accounts": picked,
        "cached": False,
        "message": "🎉 Nhận 10 acc thành công!"
    })


@app.route("/api/stats")
def api_stats():
    all_keys = get_api_keys()
    return jsonify({
        "shop_name": SHOP_NAME,
        "telegram": TELEGRAM_USERNAME,
        "mission_link": MISSION_LINK,
        "total_accounts": len(get_all_accounts()),
        "keys_in_env": len(all_keys),
        "database": "Supabase" if DB_READY else "Memory (fallback)"
    })


if __name__ == "__main__":
    print(f"✅ Loaded {len(get_all_accounts())} accounts")
    print(f"🏪 Shop: {SHOP_NAME}")
    print(f"📱 Telegram: @{TELEGRAM_USERNAME}")
    print(f"🎯 Mission: {MISSION_LINK}")
    print(f"🔑 API_KEY: {len(get_api_keys())} keys")
    print(f"🗄️  DB: {'Supabase' if DB_READY else 'Memory'}")
    app.run(host="0.0.0.0", port=5000, debug=True)
