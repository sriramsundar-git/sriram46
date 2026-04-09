import sqlite3, os, hashlib
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.db")


def _hash(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Orders
    c.execute("""CREATE TABLE IF NOT EXISTS orders (
        order_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        order_time   TEXT    NOT NULL,
        total_amount REAL    NOT NULL,
        token_number INTEGER,
        status       TEXT    NOT NULL DEFAULT 'preparing'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS order_items (
        order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id      INTEGER NOT NULL,
        item_name     TEXT    NOT NULL,
        quantity      INTEGER NOT NULL,
        unit_price    REAL    NOT NULL DEFAULT 0,
        line_total    REAL    NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders(order_id)
    )""")

    # Migrations for columns added after initial release
    for col, defn in [("token_number","INTEGER"), ("status","TEXT DEFAULT 'preparing'")]:
        try:
            c.execute(f"ALTER TABLE orders ADD COLUMN {col} {defn}")
        except Exception: pass
    try:
        c.execute("ALTER TABLE order_items ADD COLUMN unit_price REAL NOT NULL DEFAULT 0")
    except Exception: pass

    # Backfill NULL status for orders created before this column existed
    c.execute("UPDATE orders SET status='preparing' WHERE status IS NULL")
    # Backfill NULL token_number with a sequential value based on order_id
    c.execute("UPDATE orders SET token_number = (order_id % 99) + 1 WHERE token_number IS NULL")

    # Staff
    c.execute("""CREATE TABLE IF NOT EXISTS staff (
        staff_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT    NOT NULL,
        username   TEXT    NOT NULL UNIQUE,
        password   TEXT    NOT NULL,
        role       TEXT    NOT NULL DEFAULT 'cashier',
        is_active  INTEGER NOT NULL DEFAULT 1,
        created_at TEXT    NOT NULL
    )""")

    # Feedback
    c.execute("""CREATE TABLE IF NOT EXISTS feedback (
        feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id    INTEGER,
        text        TEXT    NOT NULL,
        sentiment   TEXT    NOT NULL DEFAULT 'neutral',
        created_at  TEXT    NOT NULL
    )""")

    # Time-based schedule overrides
    c.execute("""CREATE TABLE IF NOT EXISTS item_schedule (
        schedule_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id      INTEGER NOT NULL UNIQUE,
        start_hour   INTEGER NOT NULL,
        end_hour     INTEGER NOT NULL
    )""")

    # Token counter
    c.execute("""CREATE TABLE IF NOT EXISTS token_counter (
        id    INTEGER PRIMARY KEY DEFAULT 1,
        value INTEGER NOT NULL DEFAULT 0
    )""")
    c.execute("INSERT OR IGNORE INTO token_counter (id,value) VALUES (1,0)")

    # Seed default admin
    c.execute("SELECT COUNT(*) FROM staff WHERE role='manager'")
    if c.fetchone()[0] == 0:
        c.execute("""INSERT INTO staff (name,username,password,role,is_active,created_at)
                     VALUES (?,?,?,?,1,?)""",
                  ("Admin","admin",_hash("admin123"),"manager",
                   datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    conn.commit()
    conn.close()


# ── Token ──────────────────────────────────────────────────────────────────

def next_token():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE token_counter SET value = value + 1 WHERE id=1")
    c.execute("SELECT value FROM token_counter WHERE id=1")
    val = c.fetchone()[0]
    # Reset after 99
    if val > 99:
        c.execute("UPDATE token_counter SET value=1 WHERE id=1")
        val = 1
    conn.commit()
    conn.close()
    return val

def reset_token_counter():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE token_counter SET value=0 WHERE id=1")
    conn.commit()
    conn.close()


# ── Orders ─────────────────────────────────────────────────────────────────

def save_order(cart_summary, total_amount):
    token = next_token()
    conn  = sqlite3.connect(DB_PATH)
    c     = conn.cursor()
    order_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO orders (order_time,total_amount,token_number,status) VALUES (?,?,?,'preparing')",
              (order_time, total_amount, token))
    order_id = c.lastrowid
    for item in cart_summary:
        c.execute("""INSERT INTO order_items (order_id,item_name,quantity,unit_price,line_total)
                     VALUES (?,?,?,?,?)""",
                  (order_id, item["item_name"], item["qty"],
                   item.get("price",0), item["line_total"]))
    conn.commit()
    conn.close()
    return order_id, token

def get_order_by_id(order_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE order_id=?", (order_id,))
    row = c.fetchone()
    if not row: conn.close(); return None
    order = dict(row)
    c.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,))
    order["order_lines"] = [dict(r) for r in c.fetchall()]
    conn.close()
    return order

def get_all_orders():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM orders ORDER BY order_id DESC")
    orders = [dict(row) for row in c.fetchall()]
    for order in orders:
        c.execute("SELECT * FROM order_items WHERE order_id=?", (order["order_id"],))
        order["order_lines"] = [dict(r) for r in c.fetchall()]
    conn.close()
    return orders

def get_active_orders():
    """Orders with status 'preparing' — for kitchen display."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM orders WHERE status='preparing' ORDER BY order_id ASC")
    orders = [dict(row) for row in c.fetchall()]
    for order in orders:
        c.execute("SELECT * FROM order_items WHERE order_id=?", (order["order_id"],))
        order["order_lines"] = [dict(r) for r in c.fetchall()]
    conn.close()
    return orders

def update_order_status(order_id, status):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE orders SET status=? WHERE order_id=?", (status, order_id))
    conn.commit()
    conn.close()

def get_dashboard_stats():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT COUNT(*) as total_orders, COALESCE(SUM(total_amount),0) as total_revenue FROM orders")
    summary = dict(c.fetchone())

    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("""SELECT COUNT(*) as today_orders, COALESCE(SUM(total_amount),0) as today_revenue
                 FROM orders WHERE order_time LIKE ?""", (today+"%",))
    today_data = dict(c.fetchone())

    c.execute("""SELECT item_name, SUM(quantity) as total_qty, SUM(line_total) as total_rev
                 FROM order_items GROUP BY item_name ORDER BY total_qty DESC LIMIT 6""")
    top_items = [dict(r) for r in c.fetchall()]

    c.execute("""SELECT DATE(order_time) as day, COUNT(*) as count, SUM(total_amount) as revenue
                 FROM orders WHERE order_time >= DATE('now','-6 days')
                 GROUP BY DATE(order_time) ORDER BY day ASC""")
    daily_stats = [dict(r) for r in c.fetchall()]

    c.execute("""SELECT item_name, SUM(line_total) as revenue
                 FROM order_items GROUP BY item_name ORDER BY revenue DESC LIMIT 8""")
    item_revenue = [dict(r) for r in c.fetchall()]

    # Hourly velocity for demand forecasting
    c.execute("""SELECT oi.item_name,
                        COUNT(*) as orders_today,
                        SUM(oi.quantity) as qty_today
                 FROM order_items oi
                 JOIN orders o ON oi.order_id=o.order_id
                 WHERE o.order_time LIKE ?
                 GROUP BY oi.item_name""", (today+"%",))
    today_velocity = [dict(r) for r in c.fetchall()]

    avg_val = (summary["total_revenue"]/summary["total_orders"]
               if summary["total_orders"]>0 else 0)
    conn.close()

    return {
        "total_orders"    : summary["total_orders"],
        "total_revenue"   : round(summary["total_revenue"], 2),
        "today_orders"    : today_data["today_orders"],
        "today_revenue"   : round(today_data["today_revenue"], 2),
        "avg_order_value" : round(avg_val, 2),
        "top_items"       : top_items,
        "daily_stats"     : daily_stats,
        "item_revenue"    : item_revenue,
        "today_velocity"  : today_velocity,
    }


# ── Feedback ───────────────────────────────────────────────────────────────

def save_feedback(order_id, text, sentiment):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO feedback (order_id,text,sentiment,created_at) VALUES (?,?,?,?)",
                 (order_id, text, sentiment,
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def get_all_feedback():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM feedback ORDER BY feedback_id DESC")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ── Time schedule ──────────────────────────────────────────────────────────

def get_all_schedules():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM item_schedule")
    rows = {r["item_id"]: dict(r) for r in c.fetchall()}
    conn.close()
    return rows

def set_schedule(item_id, start_hour, end_hour):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT INTO item_schedule (item_id,start_hour,end_hour)
                    VALUES (?,?,?)
                    ON CONFLICT(item_id) DO UPDATE SET start_hour=?,end_hour=?""",
                 (item_id, start_hour, end_hour, start_hour, end_hour))
    conn.commit()
    conn.close()

def delete_schedule(item_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM item_schedule WHERE item_id=?", (item_id,))
    conn.commit()
    conn.close()


# ── Staff ──────────────────────────────────────────────────────────────────

def get_all_staff():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT staff_id,name,username,role,is_active,created_at FROM staff ORDER BY staff_id")
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows

def add_staff(name, username, password, role):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""INSERT INTO staff (name,username,password,role,is_active,created_at)
                        VALUES (?,?,?,?,1,?)""",
                     (name, username, _hash(password), role,
                      datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        c = conn.cursor()
        c.execute("SELECT last_insert_rowid()")
        rid = c.fetchone()[0]
        conn.close()
        return True, rid
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Username already exists."

def update_staff(staff_id, name, role, is_active):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE staff SET name=?,role=?,is_active=? WHERE staff_id=?",
                 (name, role, int(is_active), staff_id))
    conn.commit()
    conn.close()

def delete_staff(staff_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM staff WHERE role='manager' AND is_active=1")
    mgr_count = c.fetchone()[0]
    c.execute("SELECT role FROM staff WHERE staff_id=?", (staff_id,))
    row = c.fetchone()
    if row and row[0]=="manager" and mgr_count<=1:
        conn.close()
        return False, "Cannot delete the last manager account."
    conn.execute("DELETE FROM staff WHERE staff_id=?", (staff_id,))
    conn.commit()
    conn.close()
    return True, "Deleted."

def reset_staff_password(staff_id, new_password):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE staff SET password=? WHERE staff_id=?",
                 (_hash(new_password), staff_id))
    conn.commit()
    conn.close()

def verify_staff(username, password):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""SELECT staff_id,name,username,role,is_active
                 FROM staff WHERE username=? AND password=?""",
              (username, _hash(password)))
    row = c.fetchone()
    conn.close()
    if row and dict(row)["is_active"]:
        return dict(row)
    return None
