import os
import json
import uuid
import bcrypt
import psycopg2
from psycopg2 import pool, errors, extras
from psycopg2.extensions import register_adapter, AsIs
from flask import Flask, render_template, Response, jsonify, request, send_from_directory, session
from functools import wraps
from datetime import timedelta, datetime, timezone
from urllib.parse import quote

def adapt_uuid(val):
    return AsIs(f"'{val}'")
register_adapter(uuid.UUID, adapt_uuid)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "infinity-secret-key-change-in-production")
app.permanent_session_lifetime = timedelta(days=30)

db_pool = pool.SimpleConnectionPool(
    minconn=2,
    maxconn=10,
    host=os.environ.get("DB_HOST", "localhost"),
    database=os.environ.get("DB_NAME", "ahmedx3"),
    user=os.environ.get("DB_USER", "ahmedx3"),
    password=os.environ.get("DB_PASSWORD", "AHMEDX3COMai"),
    port=int(os.environ.get("DB_PORT", 5432)),
    options="-c timezone=Africa/Cairo"
)

TABLE_MAP = {
    "MEN": "products_men",
    "YOUTH": "products_youth",
    "CHILDREN": "products_children"
}

BACKGROUND_FOLDER = r"D:\projects\one\backgrounds"
VIDEO_BASE_FOLDER = r"D:\projects\one\products"

def init_database():
    conn = db_pool.getconn()
    try:
        cursor = conn.cursor()
        cursor.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                first_name VARCHAR(50) NOT NULL,
                last_name VARCHAR(50) NOT NULL,
                email VARCHAR(255) NOT NULL UNIQUE,
                phone VARCHAR(20),
                password_hash VARCHAR(255) NOT NULL,
                remember_me BOOLEAN DEFAULT FALSE,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        wheel_columns = [
            ("total_spins", "INTEGER DEFAULT 0"), ("last_spin_date", "DATE"),
            ("last_prize_name", "VARCHAR(50)"), ("last_prize_type", "VARCHAR(20)"),
            ("last_prize_value", "NUMERIC(10,2) DEFAULT 0"), ("total_cash_earned", "NUMERIC(12,2) DEFAULT 0"),
            ("total_coins_earned", "NUMERIC(12,2) DEFAULT 0"), ("rewards_history", "JSONB DEFAULT '[]'::jsonb")
        ]
        for col_name, col_def in wheel_columns:
            cursor.execute(f"""
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='{col_name}') THEN
                        ALTER TABLE users ADD COLUMN {col_name} {col_def};
                    END IF;
                END $$;
            """)
        cursor.execute("""DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_prize_type' AND conrelid = 'users'::regclass) THEN ALTER TABLE users ADD CONSTRAINT chk_prize_type CHECK (last_prize_type IN ('cash_egp', 'gold_coin', 'no_reward') OR last_prize_type IS NULL); END IF; END $$;""")
        cursor.execute("CREATE OR REPLACE FUNCTION update_updated_at() RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;")
        cursor.execute("""DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_users_updated_at') THEN CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at(); END IF; END $$;""")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_last_spin ON users(last_spin_date)')
        cursor.execute("""CREATE TABLE IF NOT EXISTS user_sessions (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, token VARCHAR(512) NOT NULL UNIQUE, expires_at TIMESTAMP NOT NULL, created_at TIMESTAMP DEFAULT NOW())""")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_token ON user_sessions(token)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON user_sessions(user_id)')
        
        # ✅ جداول الطلبات
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                total_price NUMERIC(10,2) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'shipped', 'delivered', 'cancelled')),
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS order_items (
                id SERIAL PRIMARY KEY,
                order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL,
                department VARCHAR(20) NOT NULL,
                product_name VARCHAR(255) NOT NULL,
                price NUMERIC(10,2) NOT NULL,
                quantity INTEGER DEFAULT 1,
                price_before NUMERIC(10,2),
                discount_percent NUMERIC(5,2) DEFAULT 0,
                price_after NUMERIC(10,2),
                video_url TEXT,
                material VARCHAR(100)
            )
        """)
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at DESC)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id)')
        
        product_cols = [("price_before", "NUMERIC(10,2)"), ("discount", "NUMERIC(5,2) DEFAULT 0"), ("price_after", "NUMERIC(10,2)"), ("video_url", "TEXT")]
        for tbl in ["products_men", "products_youth", "products_children"]:
            cursor.execute(f"""CREATE TABLE IF NOT EXISTS {tbl} (id SERIAL PRIMARY KEY, file_name VARCHAR(255) NOT NULL, image_data BYTEA NOT NULL, image_hash TEXT NOT NULL UNIQUE, upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            for col_name, col_def in product_cols:
                cursor.execute(f"""DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='{tbl}' AND column_name='{col_name}') THEN ALTER TABLE {tbl} ADD COLUMN {col_name} {col_def}; END IF; END $$;""")
        conn.commit()
        cursor.close()
        print("✅ Database initialized successfully.")
    except Exception as e:
        conn.rollback()
        print(f"❌ init_database ERROR: {e}")
    finally:
        if conn: db_pool.putconn(conn)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session: return jsonify({"error": "Unauthorized", "message": "يجب تسجيل الدخول أولاً"}), 401
        return f(*args, **kwargs)
    return decorated

def get_current_user():
    if 'user_id' not in session: return None
    conn = db_pool.getconn()
    try:
        cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
        cursor.execute("SELECT id, first_name, last_name, email, phone, is_active, total_spins, last_spin_date, total_cash_earned, total_coins_earned, last_prize_name, last_prize_type, last_prize_value, rewards_history FROM users WHERE id = %s", (session['user_id'],))
        return cursor.fetchone()
    except: return None
    finally:
        if conn: db_pool.putconn(conn)

# 🖼️ دالة مساعدة لإنشاء رابط الصورة للمنتج
def build_image_url(department, product_id):
    """
    ينشئ رابط الصورة للمنتج بناءً على القسم ومعرف المنتج
    """
    if not department or not product_id:
        return None
    dept_lower = department.lower()
    if dept_lower not in ['men', 'youth', 'children']:
        return None
    # نستخدم quote لضمان سلامة الرابط
    return f"/image/{dept_lower}/{product_id}"

@app.route("/")
def start(): return render_template("start.html")
@app.route("/home")
def home(): return render_template("original.html")
@app.route("/login")
def login_page(): return render_template("login.html")
@app.route("/register")
def register_page(): return render_template("register.html")
@app.route("/wheel")
def wheel_page(): return render_template("wheel.html")
@app.route("/department/men")
def men(): return render_template("men.html")
@app.route("/department/youth")
def youth(): return render_template("youth.html")
@app.route("/department/children")
def children(): return render_template("children.html")
@app.route("/buy")
def buy_page(): return render_template("buy.html")

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json(silent=True)
    if not data: return jsonify({"error": "Invalid request body"}), 400
    first_name = data.get("first_name", "").strip()
    last_name = data.get("last_name", "").strip()
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    password = data.get("password", "")
    if not all([first_name, last_name, email, password]): return jsonify({"error": "All required fields must be filled"}), 400
    if len(password) < 8: return jsonify({"error": "Password must be at least 8 characters"}), 400
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    new_id = uuid.uuid4()
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (id, first_name, last_name, email, phone, password_hash) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (new_id, first_name, last_name, email, phone or None, password_hash))
        conn.commit()
        return jsonify({"message": "Account created successfully", "user_id": str(new_id)}), 201
    except errors.UniqueViolation:
        if conn: conn.rollback()
        return jsonify({"error": "يوجد حساب مسبق بهذا البريد الإلكتروني"}), 409
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True)
    if not data: return jsonify({"error": "Invalid request body"}), 400
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    remember = data.get("remember", False)
    if not email or not password: return jsonify({"error": "Email and password are required"}), 400
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute("SELECT id, first_name, last_name, email, password_hash, is_active FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        cursor.close()
        if not user: return jsonify({"error": "Invalid email or password"}), 401
        if not user[5]: return jsonify({"error": "This account has been deactivated"}), 403
        if not bcrypt.checkpw(password.encode("utf-8"), user[4].encode("utf-8")): return jsonify({"error": "Invalid email or password"}), 401
        session.permanent = bool(remember)
        session["user_id"] = str(user[0])
        session["user_name"] = f"{user[1]} {user[2]}"
        session["user_email"] = user[3]
        return jsonify({"message": "Login successful", "user": {"id": str(user[0]), "name": f"{user[1]} {user[2]}", "email": user[3]}}), 200
    except Exception as e:
        print(f"❌ LOGIN ERROR: {e}")
        return jsonify({"error": "Server error"}), 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/api/auth/logout", methods=["POST"])
@login_required
def logout():
    uid = session.get("user_id")
    if uid:
        conn = db_pool.getconn()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_sessions WHERE user_id = %s", (uid,))
            conn.commit()
        except: pass
        finally:
            if conn: db_pool.putconn(conn)
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200

@app.route("/api/auth/me")
@login_required
def me():
    user = get_current_user()
    if not user: return jsonify({"error": "User not found"}), 404
    return jsonify({
        "user_id": str(user['id']), "name": f"{user['first_name']} {user['last_name']}", "email": user['email'], "phone": user['phone'],
        "total_spins": user['total_spins'] or 0, "total_cash_earned": float(user['total_cash_earned'] or 0), "total_coins_earned": float(user['total_coins_earned'] or 0),
        "last_prize_name": user['last_prize_name'], "last_prize_type": user['last_prize_type'], "last_spin_date": user['last_spin_date'].isoformat() if user['last_spin_date'] else None
    })

@app.route("/api/orders/count")
@login_required
def get_orders_count():
    uid = session.get("user_id")
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM orders 
            WHERE user_id = %s AND status != 'cancelled'
        """, (uid,))
        count = cursor.fetchone()[0]
        cursor.close()
        return jsonify({
            "success": True,
            "orders_count": int(count),
            "badge_text": str(count) if count > 0 else ""
        }), 200
    except Exception as e:
        print(f"❌ get_orders_count ERROR: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/api/wheel/config")
def wheel_config():
    return jsonify({"prizes": [
        {"id":"p01","name":"10 ج.م","prize_type":"cash_egp","value":10,"weight":15,"color":"#3b82f6"},
        {"id":"p02","name":"5 ج.م","prize_type":"cash_egp","value":5,"weight":20,"color":"#6366f1"},
        {"id":"p03","name":"15 عملة ذهبية","prize_type":"gold_coin","value":15,"weight":12,"color":"#f59e0b"},
        {"id":"p04","name":"10 عملات ذهبية","prize_type":"gold_coin","value":10,"weight":15,"color":"#d97706"},
        {"id":"p05","name":"5 عملات ذهبية","prize_type":"gold_coin","value":5,"weight":18,"color":"#b45309"},
        {"id":"p06","name":"50 عملة ذهبية","prize_type":"gold_coin","value":50,"weight":5,"color":"#10b981"},
        {"id":"p07","name":"20 ج.م","prize_type":"cash_egp","value":20,"weight":8,"color":"#ef4444"},
        {"id":"p08","name":"حظ أوفر 🍀","prize_type":"no_reward","value":0,"weight":7,"color":"#475569"}
    ]})

@app.route("/api/wheel/can-spin")
@login_required
def can_spin():
    uid = session.get("user_id")
    conn = db_pool.getconn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT last_spin_date FROM users WHERE id = %s", (uid,))
        row = cursor.fetchone()
        cursor.close()
        if not row: return jsonify({"error": "User not found"}), 404
        last_spin = row[0]
        from datetime import date
        today = date.today()
        has_spun = (last_spin is not None and last_spin == today)
        return jsonify({"can_spin": not has_spun, "message": "لقد لففت العجلة اليوم بالفعل، عد غداً!" if has_spun else "يمكنك اللف الآن", "last_spin_date": last_spin.isoformat() if last_spin else None})
    except Exception as e:
        print(f"❌ can_spin ERROR: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/api/wheel/spin", methods=["POST"])
@login_required
def spin_wheel():
    data = request.get_json(silent=True)
    if not data or 'prize' not in data: return jsonify({"error": "Missing prize data"}), 400
    prize = data['prize']
    p_name = str(prize.get('name', ''))[:50]
    p_type = str(prize.get('prize_type', ''))
    p_value = float(prize.get('value', 0))
    if p_type not in ('cash_egp', 'gold_coin', 'no_reward'): return jsonify({"error": "Invalid prize type"}), 400
    uid = session.get("user_id")
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        from datetime import date
        today = date.today()
        cursor.execute("SELECT last_spin_date FROM users WHERE id = %s FOR UPDATE", (uid,))
        row = cursor.fetchone()
        if not row: conn.rollback(); return jsonify({"error": "User not found"}), 404
        if row[0] == today: conn.rollback(); return jsonify({"error": "لقد لففت العجلة اليوم بالفعل، عد غداً!"}), 403
        new_record = {"name": p_name, "type": p_type, "value": p_value, "date": datetime.now(timezone.utc).isoformat()}
        cursor.execute("""UPDATE users SET last_spin_date = %s, last_prize_name = %s, last_prize_type = %s, last_prize_value = %s, total_spins = COALESCE(total_spins, 0) + 1, total_cash_earned = CASE WHEN %s = 'cash_egp' THEN COALESCE(total_cash_earned, 0) + %s ELSE COALESCE(total_cash_earned, 0) END, total_coins_earned = CASE WHEN %s = 'gold_coin' THEN COALESCE(total_coins_earned, 0) + %s ELSE COALESCE(total_coins_earned, 0) END, rewards_history = (SELECT jsonb_agg(elem) FROM (SELECT %s::jsonb AS elem UNION ALL SELECT elem FROM jsonb_array_elements(COALESCE(rewards_history, '[]'::jsonb)) AS t(elem) LIMIT 50) sub) WHERE id = %s""",
            (today, p_name, p_type, p_value, p_type, p_value, p_type, p_value, json.dumps(new_record, ensure_ascii=False), uid))
        conn.commit()
        cursor.close()
        return jsonify({"success": True, "message": "تم تسجيل المكافأة بنجاح!", "prize": prize}), 200
    except Exception as e:
        if conn: conn.rollback()
        print(f"❌ spin_wheel ERROR: {e}")
        return jsonify({"error": "Server error"}), 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/api/wheel/history")
@login_required
def wheel_history():
    uid = session.get("user_id")
    conn = db_pool.getconn()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT rewards_history, total_spins, total_cash_earned, total_coins_earned FROM users WHERE id = %s", (uid,))
        row = cursor.fetchone()
        cursor.close()
        if not row: return jsonify({"error": "User not found"}), 404
        history_raw = row[0] or []
        if isinstance(history_raw, str):
            try: history_raw = json.loads(history_raw)
            except: history_raw = []
        return jsonify({"history": history_raw[:20], "total_spins": int(row[1] or 0), "total_cash_earned": float(row[2] or 0), "total_coins_earned": float(row[3] or 0)})
    except Exception as e:
        print(f"❌ wheel_history ERROR: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/api/products")
def get_products():
    search = request.args.get("search", "").strip()
    department = request.args.get("department", "").strip().upper()
    table_name = TABLE_MAP.get(department)
    if not table_name: return jsonify({"error": "Invalid department"}), 400
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cols = "id, file_name, price_before, discount, price_after, video_url"
        if search:
            cursor.execute(f"SELECT {cols} FROM {table_name} WHERE LOWER(file_name) LIKE LOWER(%s)", (f"%{search}%",))
        else:
            cursor.execute(f"SELECT {cols} FROM {table_name}")
        rows = cursor.fetchall()
        cursor.close()
        products = [{"id": str(r[0]) if isinstance(r[0], uuid.UUID) else r[0], "name": r[1].rsplit(".", 1)[0] if r[1] and "." in r[1] else r[1], "price_before": float(r[2]) if r[2] else None, "discount": float(r[3]) if r[3] else 0, "price_after": float(r[4]) if r[4] else None, "video_url": r[5], "material": "", "image_url": build_image_url(department, r[0])} for r in rows]
        return jsonify({"products": products})
    except Exception as e:
        print(f"❌ GET PRODUCTS ERROR: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/api/products/<department>/<int:product_id>")
def get_product(department, product_id):
    table_name = TABLE_MAP.get(department.upper())
    if not table_name: return jsonify({"error": "Invalid department"}), 400
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute(f"SELECT id, file_name, price_before, discount, price_after, video_url FROM {table_name} WHERE id = %s", (product_id,))
        row = cursor.fetchone()
        cursor.close()
        if not row: return jsonify({"error": "Product not found"}), 404
        name = row[1].rsplit(".", 1)[0] if row[1] and "." in row[1] else row[1]
        return jsonify({
            "id": str(row[0]) if isinstance(row[0], uuid.UUID) else row[0], 
            "name": name, 
            "price_before": float(row[2]) if row[2] else None, 
            "discount": float(row[3]) if row[3] else 0, 
            "price_after": float(row[4]) if row[4] else None, 
            "video_url": row[5],
            "image_url": build_image_url(department, product_id)
        })
    except Exception as e:
        print(f"❌ GET PRODUCT ERROR: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/image/<department>/<int:product_id>")
def get_image(department, product_id):
    table_name = TABLE_MAP.get(department.upper())
    if not table_name: return "Invalid department", 400
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute(f"SELECT image_data FROM {table_name} WHERE id = %s", (product_id,))
        row = cursor.fetchone()
        cursor.close()
        if not row or not row[0]: return "Image not found", 404
        image_bytes = row[0].tobytes() if isinstance(row[0], memoryview) else bytes(row[0])
        return Response(image_bytes, mimetype="image/jpeg")
    except Exception as e:
        print(f"❌ GET IMAGE ERROR: {e}")
        return "Server error", 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/video/<department>/<filename>")
def serve_video(department, filename):
    filename = os.path.basename(filename)
    dept_map = {"men": "men", "youth": "youth", "children": "children"}
    if department.lower() not in dept_map:
        return "Invalid department", 400
    video_folder_map = {
        "men": "men_video",
        "youth": "youth_video",
        "children": "child_video"
    }
    video_dir = os.path.join(VIDEO_BASE_FOLDER, dept_map[department.lower()], video_folder_map[department.lower()])
    video_path = os.path.join(video_dir, filename)
    if not os.path.exists(video_path):
        return jsonify({"error": "Video not found"}), 404
    return send_from_directory(video_dir, filename)

@app.route("/backgrounds/<filename>")
def backgrounds(filename):
    return send_from_directory(BACKGROUND_FOLDER, filename)

# ✅ مسارات الطلبات

@app.route("/api/orders", methods=["POST"])
@login_required
def create_order():
    try:
        data = request.get_json(silent=True)
        if not data: return jsonify({"error": "Invalid request"}), 400
        
        user_id = session.get("user_id")
        total_price = float(data.get("total_price", 0))
        product_id = int(data.get("product_id", 0))
        department = str(data.get("department", "")).upper()
        product_name = str(data.get("product_name", ""))[:255]
        price = float(data.get("price", 0))
        quantity = int(data.get("quantity", 1))
        
        if not user_id or total_price <= 0 or not product_id:
            return jsonify({"error": "Missing required fields"}), 400
        
        conn = db_pool.getconn()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO orders (user_id, total_price) VALUES (%s, %s) RETURNING id
        """, (user_id, total_price))
        order_id = cursor.fetchone()[0]
        
        cursor.execute("""
            INSERT INTO order_items (order_id, product_id, department, product_name, price, quantity)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (order_id, product_id, department, product_name, price, quantity))
        
        conn.commit()
        cursor.close()
        
        return jsonify({
            "success": True, 
            "message": "تم استلام طلبك بنجاح!", 
            "order_id": order_id,
            "order_number": f"ORD-{order_id:06d}"
        }), 201
        
    except Exception as e:
        print(f"❌ create_order ERROR: {e}")
        if conn: conn.rollback()
        return jsonify({"error": "Failed to create order"}), 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/api/orders/<int:order_id>")
@login_required
def get_order(order_id):
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
        
        cursor.execute("""
            SELECT o.id, o.user_id, o.total_price, o.created_at,
                   oi.product_id, oi.department, oi.product_name, oi.price, oi.quantity
            FROM orders o
            JOIN order_items oi ON o.id = oi.order_id
            WHERE o.id = %s AND o.user_id = %s
        """, (order_id, session.get("user_id")))
        
        order = cursor.fetchone()
        cursor.close()
        
        if not order: return jsonify({"error": "Order not found"}), 404
        
        return jsonify({
            "order_id": order["id"],
            "order_number": f"ORD-{order['id']:06d}",
            "total_price": float(order["total_price"]),
            "created_at": order["created_at"].isoformat() if order["created_at"] else None,
            "items": [{
                "product_id": order["product_id"],
                "department": order["department"],
                "product_name": order["product_name"],
                "price": float(order["price"]),
                "quantity": order["quantity"],
                "image_url": build_image_url(order["department"], order["product_id"])  # ➕ إضافة image_url
            }]
        })
        
    except Exception as e:
        print(f"❌ get_order ERROR: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn: db_pool.putconn(conn)


@app.route("/api/orders/history")
@login_required
def get_user_orders():
    """جلب جميع طلبات المستخدم مع تفاصيل كل عنصر + image_url"""
    uid = session.get("user_id")
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.id, o.total_price, o.status, o.created_at,
                   oi.id, oi.product_id, oi.department, oi.product_name, oi.price, oi.quantity,
                   oi.price_before, oi.discount_percent, oi.price_after, oi.video_url, oi.material
            FROM orders o
            JOIN order_items oi ON o.id = oi.order_id
            WHERE o.user_id = %s
            ORDER BY o.created_at DESC
        """, (uid,))
        rows = cursor.fetchall()
        cursor.close()
        
        orders = []
        current = None
        for r in rows:
            if not current or current['id'] != r[0]:
                current = {
                    'id': r[0], 'order_number': f"ORD-{r[0]:06d}",
                    'total_price': float(r[1]), 'status': r[2] or 'pending',
                    'created_at': r[3].isoformat() if r[3] else None,
                    'items': []
                }
                orders.append(current)
            
            # ➕ بناء image_url لكل عنصر
            image_url = build_image_url(r[6], r[5])  # department, product_id
            
            current['items'].append({
                'product_id': r[5], 
                'department': r[6], 
                'product_name': r[7],
                'price': float(r[8]), 
                'quantity': r[9], 
                'price_before': float(r[10]) if r[10] else None,
                'discount_percent': float(r[11]) if r[11] else 0, 
                'price_after': float(r[12]) if r[12] else None,
                'video_url': r[13],
                'material': r[14],
                'image_url': image_url  # ✅ الحقل الجديد المطلوب للواجهة الأمامية
            })
            
        return jsonify({"orders": orders})
    except Exception as e:
        print(f"❌ get_user_orders ERROR: {e}")
        return jsonify({"error": "Database error"}), 500
    finally:
        if conn: db_pool.putconn(conn)

@app.route("/my-orders")
@login_required
def my_orders_page():
    return render_template("my_orders.html")


@app.route("/api/orders/<int:order_id>", methods=["DELETE"])
@login_required
def delete_order(order_id):
    uid = session.get("user_id")
    conn = None
    try:
        conn = db_pool.getconn()
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id, status FROM orders WHERE id = %s", (order_id,))
        row = cursor.fetchone()
        
        if not row:
            return jsonify({"error": "الطلب غير موجود", "code": "NOT_FOUND"}), 404
        
        if row[0] != uid:
            return jsonify({"error": "غير مصرح لك بحذف هذا الطلب", "code": "UNAUTHORIZED"}), 403
        
        if row[1] == 'shipped':
            return jsonify({"error": "لا يمكن حذف طلب تم شحنه", "code": "NOT_ALLOWED"}), 400
        
        cursor.execute("DELETE FROM orders WHERE id = %s AND user_id = %s", (order_id, uid))
        conn.commit()
        
        return jsonify({
            "success": True, 
            "message": "✅ تم حذف الطلب بنجاح",
            "order_id": order_id
        }), 200
        
    except Exception as e:
        print(f"❌ delete_order ERROR: {e}")
        if conn: conn.rollback()
        return jsonify({"error": "فشل في حذف الطلب", "details": str(e)}), 500
    finally:
        if conn: db_pool.putconn(conn)


if __name__ == "__main__":
    print("🔄 Initializing database...")
    init_database()
    print("✅ Server starting on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000, debug=True)
