import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "orders.db")

# 初回起動時にユーザーが0件の場合のみ作成される初期管理者アカウント。
# 環境変数 INITIAL_ADMIN_USERNAME / INITIAL_ADMIN_PASSWORD で上書き可能。
DEFAULT_ADMIN_USERNAME = os.environ.get("INITIAL_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("INITIAL_ADMIN_PASSWORD", "changeme123")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            base_material TEXT
        );

        CREATE TABLE IF NOT EXISTS colors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            color_code TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            control_no TEXT,
            order_date TEXT,
            order_number TEXT,
            product_name TEXT NOT NULL,
            base_material TEXT,
            color_code TEXT,
            material_delivery_memo TEXT,
            desired_delivery TEXT,
            order_quantity INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT '進行中'
        );

        CREATE TABLE IF NOT EXISTS delivery_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            reply_date TEXT,
            reply_quantity INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS delivery_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            mold_number TEXT,
            actual_date TEXT,
            actual_quantity INTEGER NOT NULL DEFAULT 0,
            registered_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS change_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            changed_at TEXT DEFAULT (datetime('now', 'localtime')),
            change_type TEXT,
            change_detail TEXT,
            operator TEXT,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
    """)
    conn.commit()

    # マイグレーション: delivery_records に mold_number が無ければ追加
    cols = [row[1] for row in c.execute("PRAGMA table_info(delivery_records)").fetchall()]
    if "mold_number" not in cols:
        c.execute("ALTER TABLE delivery_records ADD COLUMN mold_number TEXT")
        conn.commit()

    # マイグレーション: products から quantity_per_package / package_unit を削除
    prod_cols = [row[1] for row in c.execute("PRAGMA table_info(products)").fetchall()]
    if "quantity_per_package" in prod_cols or "package_unit" in prod_cols:
        c.executescript("""
            PRAGMA foreign_keys = OFF;
            CREATE TABLE products_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                base_material TEXT
            );
            INSERT INTO products_new (id, name, base_material)
                SELECT id, name, base_material FROM products;
            DROP TABLE products;
            ALTER TABLE products_new RENAME TO products;
            PRAGMA foreign_keys = ON;
        """)
        conn.commit()

    # 初回起動時: ユーザーが0件なら初期管理者ユーザーを作成
    user_count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if user_count == 0:
        c.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (DEFAULT_ADMIN_USERNAME, generate_password_hash(DEFAULT_ADMIN_PASSWORD))
        )
        conn.commit()
        print(f"[init_db] 初期管理者ユーザーを作成しました: username='{DEFAULT_ADMIN_USERNAME}'")

    conn.close()
