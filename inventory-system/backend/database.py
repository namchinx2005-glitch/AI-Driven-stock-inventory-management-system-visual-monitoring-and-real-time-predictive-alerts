"""
Persistence & Analytics Layer (Chapter 3, section 3.3.1 / 3.6.2).
Two operational tables: stock_logs (periodic counts) and sales_events (inventory drops).
"""
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

DB_PATH = "inventory.db"
_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_conn():
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'manager', 'sales', 'accountant')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                price REAL NOT NULL DEFAULT 0.0,
                category TEXT,
                sku TEXT,
                barcode TEXT,
                image_url TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS stock_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                item_count INTEGER NOT NULL,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );

            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                movement_type TEXT NOT NULL CHECK(movement_type IN ('camera_receipt', 'manual_receipt', 'sale')),
                note TEXT,
                user_id INTEGER,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(product_id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS sales_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                qty_sold INTEGER NOT NULL,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                sale_type TEXT NOT NULL DEFAULT 'auto' CHECK(sale_type IN ('auto', 'pos')),
                user_id INTEGER,
                FOREIGN KEY (product_id) REFERENCES products(product_id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS pos_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                total_amount REAL NOT NULL,
                items_count INTEGER NOT NULL,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                payment_method TEXT DEFAULT 'cash',
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS pos_transaction_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                total_price REAL NOT NULL,
                FOREIGN KEY (transaction_id) REFERENCES pos_transactions(transaction_id),
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sms_sent INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS sms_dispatch_log (
                product_id TEXT PRIMARY KEY,
                last_sent TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_stock_product_ts ON stock_logs(product_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_sales_product_ts ON sales_events(product_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_sales_user ON sales_events(user_id);
            CREATE INDEX IF NOT EXISTS idx_pos_transactions_user ON pos_transactions(user_id);
            CREATE INDEX IF NOT EXISTS idx_pos_transactions_ts ON pos_transactions(timestamp);
            CREATE INDEX IF NOT EXISTS idx_pos_items_transaction ON pos_transaction_items(transaction_id);
            """
        )
        
        # Handle migration from old schema to new schema
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stock_logs)")}
        if "item_count" not in columns and "count" in columns:
            conn.execute("ALTER TABLE stock_logs RENAME COLUMN count TO item_count")
        
        # Add new columns to sales_events if they don't exist
        sales_columns = {row[1] for row in conn.execute("PRAGMA table_info(sales_events)")}
        if "sale_type" not in sales_columns:
            conn.execute("ALTER TABLE sales_events ADD COLUMN sale_type TEXT NOT NULL DEFAULT 'auto'")
        if "user_id" not in sales_columns:
            conn.execute("ALTER TABLE sales_events ADD COLUMN user_id INTEGER")

        # Migrate the initial two-role table so existing installations can add
        # admins and accountants too.
        users_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
        if "sales_person', 'manager" in users_sql:
            conn.executescript("""
                ALTER TABLE users RENAME TO users_legacy;
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'manager', 'sales', 'accountant')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, is_active INTEGER NOT NULL DEFAULT 1
                );
                INSERT INTO users (id, username, password_hash, full_name, role, created_at, is_active)
                SELECT id, username, password_hash, full_name,
                       CASE WHEN role = 'sales_person' THEN 'sales' ELSE role END,
                       created_at, is_active FROM users_legacy;
                DROP TABLE users_legacy;
            """)


def write_stock_log(product_id: str, count: int, ts: str = None):
    ts = ts or datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO stock_logs (product_id, item_count, timestamp) VALUES (?, ?, ?)",
            (product_id, count, ts),
        )


def receive_stock(product_id: str, quantity: int, movement_type: str, user_id: int = None, note: str = ""):
    """Append an auditable receipt and write the resulting on-hand count."""
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero")
    if not get_product(product_id):
        raise ValueError("Product not found")
    current = get_latest_count(product_id) or 0
    new_count = current + quantity
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO stock_movements (product_id, quantity, movement_type, note, user_id) VALUES (?, ?, ?, ?, ?)",
            (product_id, quantity, movement_type, note, user_id),
        )
        conn.execute("INSERT INTO stock_logs (product_id, item_count, timestamp) VALUES (?, ?, ?)",
                     (product_id, new_count, datetime.utcnow().isoformat()))
    return new_count


def set_stock_count(product_id: str, count: int, user_id: int = None, note: str = "Manual stock count"):
    """Set a physical count exactly, retaining the correction in the audit log."""
    if count < 0:
        raise ValueError("Stock cannot be negative")
    if not get_product(product_id):
        raise ValueError("Product not found")
    previous = get_latest_count(product_id) or 0
    with get_conn() as conn:
        conn.execute("INSERT INTO stock_movements (product_id, quantity, movement_type, note, user_id) VALUES (?, ?, 'manual_receipt', ?, ?)",
                     (product_id, count - previous, note, user_id))
        conn.execute("INSERT INTO stock_logs (product_id, item_count, timestamp) VALUES (?, ?, ?)",
                     (product_id, count, datetime.utcnow().isoformat()))
    return count


def get_latest_count(product_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT item_count FROM stock_logs WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1",
            (product_id,),
        ).fetchone()
        return row["item_count"] if row else None


def get_previous_count(product_id: str):
    """Second-most-recent count, used to detect drops (sales_events)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT item_count FROM stock_logs WHERE product_id = ? ORDER BY timestamp DESC LIMIT 2",
            (product_id,),
        ).fetchall()
        return rows[1]["item_count"] if len(rows) > 1 else None


def log_sales_event(product_id: str, qty_sold: int, ts: str = None, sale_type: str = 'auto', user_id: int = None):
    ts = ts or datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sales_events (product_id, qty_sold, timestamp, sale_type, user_id) VALUES (?, ?, ?, ?, ?)",
            (product_id, qty_sold, ts, sale_type, user_id),
        )


def get_daily_sales(product_id: str, days: int):
    """Returns a list of (date_str, total_qty_sold) for the last `days` days, oldest first."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT substr(timestamp, 1, 10) AS day, SUM(qty_sold) AS total
            FROM sales_events
            WHERE product_id = ? AND timestamp >= ?
            GROUP BY day
            ORDER BY day ASC
            """,
            (product_id, since),
        ).fetchall()
        return [(r["day"], r["total"]) for r in rows]


def record_alert(product_id: str, level: str, message: str, sms_sent: bool, ts: str = None):
    ts = ts or datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO alerts (product_id, level, message, timestamp, sms_sent) VALUES (?, ?, ?, ?, ?)",
            (product_id, level, message, ts, int(sms_sent)),
        )


def get_recent_alerts(limit: int = 20):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_last_sms_timestamp(product_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT last_sent FROM sms_dispatch_log WHERE product_id = ?", (product_id,)
        ).fetchone()
        return datetime.fromisoformat(row["last_sent"]) if row else datetime.min


def update_sms_timestamp(product_id: str, ts: datetime = None):
    ts = ts or datetime.utcnow()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sms_dispatch_log (product_id, last_sent) VALUES (?, ?)
            ON CONFLICT(product_id) DO UPDATE SET last_sent = excluded.last_sent
            """,
            (product_id, ts.isoformat()),
        )


# User Management Functions
def create_user(username: str, password_hash: str, full_name: str, role: str):
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users (username, password_hash, full_name, role)
            VALUES (?, ?, ?, ?)
            """,
            (username, password_hash, full_name, role),
        )
        return cursor.lastrowid


def get_user_by_username(username: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_users():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def update_user(user_id: int, **kwargs):
    allowed_fields = ['full_name', 'role', 'is_active']
    updates = [f"{k} = ?" for k in kwargs.keys() if k in allowed_fields]
    if not updates:
        return False
    
    values = [v for k, v in kwargs.items() if k in allowed_fields]
    values.append(user_id)
    
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
            values
        )
    return True


def delete_user(user_id: int):
    """Remove a user account after the API has checked authorization rules."""
    with get_conn() as conn:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0


# Product Management Functions
def create_product(product_id: str, name: str, description: str = None, price: float = 0.0, 
                   category: str = None, sku: str = None, barcode: str = None, image_url: str = None):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO products (product_id, name, description, price, category, sku, barcode, image_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (product_id, name, description, price, category, sku, barcode, image_url),
        )


def get_product(product_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE product_id = ?", (product_id,)
        ).fetchone()
        return dict(row) if row else None


def get_all_products():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY name ASC").fetchall()
        return [dict(r) for r in rows]


def update_product(product_id: str, **kwargs):
    allowed_fields = ['name', 'description', 'price', 'category', 'sku', 'barcode', 'image_url']
    updates = [f"{k} = ?" for k in kwargs.keys() if k in allowed_fields]
    if not updates:
        return False
    
    values = [v for k, v in kwargs.items() if k in allowed_fields]
    values.append(datetime.utcnow().isoformat())
    values.append(product_id)
    
    with get_conn() as conn:
        conn.execute(
            f"UPDATE products SET {', '.join(updates)}, updated_at = ? WHERE product_id = ?",
            values
        )
    return True


def delete_product(product_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM products WHERE product_id = ?", (product_id,))


# POS Transaction Functions
def create_pos_transaction(user_id: int, items: list, total_amount: float, payment_method: str = 'cash'):
    import uuid
    if not items:
        raise ValueError("Cart is empty")
    transaction_id = str(uuid.uuid4())

    with get_conn() as conn:
        # Aggregate first. This prevents a client from adding the same SKU in
        # two lines and selling more than its on-hand quantity.
        requested = {}
        for item in items:
            product_id = item.get('product_id')
            try:
                quantity = int(item.get('quantity', 0))
            except (TypeError, ValueError):
                raise ValueError("Sale quantity must be a whole number")
            if not product_id or quantity <= 0:
                raise ValueError("Sale quantity must be greater than zero")
            requested[product_id] = requested.get(product_id, 0) + quantity

        lines, calculated_total = [], 0.0
        for product_id, quantity in requested.items():
            product = conn.execute("SELECT price FROM products WHERE product_id = ?", (product_id,)).fetchone()
            if not product:
                raise ValueError(f"Unknown product: {product_id}")
            latest = conn.execute("SELECT item_count FROM stock_logs WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1", (product_id,)).fetchone()
            available = latest['item_count'] if latest else 0
            if available <= 0:
                raise ValueError(f"{product_id} is out of stock and cannot be sold")
            if quantity > available:
                raise ValueError(f"Only {available} unit(s) of {product_id} are available")
            unit_price = float(product['price'])
            lines.append((product_id, quantity, unit_price, available))
            calculated_total += quantity * unit_price

        # Create transaction record
        conn.execute(
            """
            INSERT INTO pos_transactions (transaction_id, user_id, total_amount, items_count, payment_method)
            VALUES (?, ?, ?, ?, ?)
            """,
            (transaction_id, user_id, calculated_total, len(lines), payment_method),
        )
        
        # Add transaction items
        for product_id, quantity, unit_price, available in lines:
            conn.execute(
                """
                INSERT INTO pos_transaction_items (transaction_id, product_id, quantity, unit_price, total_price)
                VALUES (?, ?, ?, ?, ?)
                """,
                (transaction_id, product_id, quantity, unit_price, quantity * unit_price),
            )
            
            # Log sale and immediately reduce the operational count so POS sales
            # appear in the dashboard/low-stock alerts without waiting for camera.
            conn.execute(
                "INSERT INTO sales_events (product_id, qty_sold, timestamp, sale_type, user_id) VALUES (?, ?, ?, 'pos', ?)",
                (product_id, quantity, datetime.utcnow().isoformat(), user_id),
            )
            new_count = available - quantity
            conn.execute("INSERT INTO stock_logs (product_id, item_count, timestamp) VALUES (?, ?, ?)",
                         (product_id, new_count, datetime.utcnow().isoformat()))
    
    return transaction_id


def get_sales_trend(product_id: str, recent_days: int = 7):
    """Compare recent sales to the preceding equal period for restock advice."""
    now = datetime.utcnow()
    recent_start = (now - timedelta(days=recent_days)).isoformat()
    previous_start = (now - timedelta(days=recent_days * 2)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT
                   COALESCE(SUM(CASE WHEN timestamp >= ? THEN qty_sold ELSE 0 END), 0) AS recent,
                   COALESCE(SUM(CASE WHEN timestamp >= ? AND timestamp < ? THEN qty_sold ELSE 0 END), 0) AS previous
               FROM sales_events WHERE product_id = ?""",
            (recent_start, previous_start, recent_start, product_id),
        ).fetchone()
    return {"recent": row["recent"], "previous": row["previous"]}


def get_pos_transactions(limit: int = 50, user_id: int = None):
    with get_conn() as conn:
        if user_id:
            rows = conn.execute(
                """
                SELECT t.*, u.full_name as cashier_name 
                FROM pos_transactions t
                JOIN users u ON t.user_id = u.id
                WHERE t.user_id = ?
                ORDER BY t.timestamp DESC
                LIMIT ?
                """,
                (user_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT t.*, u.full_name as cashier_name 
                FROM pos_transactions t
                JOIN users u ON t.user_id = u.id
                ORDER BY t.timestamp DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_transaction_items(transaction_id: str):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT ti.*, p.name as product_name 
            FROM pos_transaction_items ti
            JOIN products p ON ti.product_id = p.product_id
            WHERE ti.transaction_id = ?
            """,
            (transaction_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# Analytics Functions
def get_most_purchased_products(days: int = 30, limit: int = 10):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT se.product_id, p.name, SUM(se.qty_sold) as total_sold, COUNT(*) as transaction_count
            FROM sales_events se
            JOIN products p ON se.product_id = p.product_id
            WHERE se.timestamp >= ?
            GROUP BY se.product_id
            ORDER BY total_sold DESC
            LIMIT ?
            """,
            (since, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def get_sales_by_category(days: int = 30):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.category, SUM(se.qty_sold) as total_sold, 
                   SUM(se.qty_sold * p.price) as total_revenue
            FROM sales_events se
            JOIN products p ON se.product_id = p.product_id
            WHERE se.timestamp >= ? AND p.category IS NOT NULL
            GROUP BY p.category
            ORDER BY total_revenue DESC
            """,
            (since,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_daily_revenue(days: int = 30):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT substr(timestamp, 1, 10) as day, 
                   SUM(qty_sold * (SELECT price FROM products WHERE product_id = se.product_id)) as revenue
            FROM sales_events se
            WHERE se.timestamp >= ?
            GROUP BY day
            ORDER BY day ASC
            """,
            (since,)
        ).fetchall()
        return [(r["day"], r["revenue"]) for r in rows]


def get_sales_analysis(start_date: str, end_date: str):
    """Date-bounded sales summary for the dashboard analytics screen.

    Dates are inclusive at the UI level; SQLite's date() keeps the comparison
    correct for both ISO timestamps and existing seeded records.
    """
    with get_conn() as conn:
        daily = conn.execute(
            """
            SELECT date(se.timestamp) AS day, SUM(se.qty_sold) AS units_sold,
                   SUM(se.qty_sold * p.price) AS revenue
            FROM sales_events se JOIN products p ON p.product_id = se.product_id
            WHERE date(se.timestamp) BETWEEN date(?) AND date(?)
            GROUP BY date(se.timestamp) ORDER BY day
            """, (start_date, end_date)).fetchall()
        top = conn.execute(
            """
            SELECT se.product_id, p.name, p.category, SUM(se.qty_sold) AS total_sold,
                   SUM(se.qty_sold * p.price) AS revenue
            FROM sales_events se JOIN products p ON p.product_id = se.product_id
            WHERE date(se.timestamp) BETWEEN date(?) AND date(?)
            GROUP BY se.product_id ORDER BY total_sold DESC LIMIT 10
            """, (start_date, end_date)).fetchall()
    daily_out = [dict(row) for row in daily]
    top_out = [dict(row) for row in top]
    best_day = max(daily_out, key=lambda row: row["revenue"], default=None)
    return {"daily": daily_out, "top_products": top_out, "best_day": best_day,
            "total_revenue": sum(row["revenue"] or 0 for row in daily_out),
            "total_units": sum(row["units_sold"] or 0 for row in daily_out)}


def get_user_performance(user_id: int, days: int = 30):
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT COUNT(DISTINCT substr(se.timestamp, 1, 10)) as days_worked,
                   COUNT(*) as total_transactions,
                   SUM(se.qty_sold) as total_items_sold,
                   SUM(se.qty_sold * p.price) as total_revenue
            FROM sales_events se
            JOIN products p ON se.product_id = p.product_id
            WHERE se.user_id = ? AND se.timestamp >= ?
            """,
            (user_id, since)
        ).fetchone()
        return dict(rows) if rows else None
